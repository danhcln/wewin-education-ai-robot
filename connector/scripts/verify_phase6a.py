"""Read-only real-cache ASGI/MCP verification; no sockets or outside requests."""
import argparse
from contextlib import ExitStack
import importlib
import json
import logging
import os
import re
from pathlib import Path
import secrets
import sys
import types
from unittest.mock import patch
ROOT=Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))


def verify(database):
    with ExitStack() as stack:
        log=types.ModuleType('src.utils.logger');log.logger=logging.getLogger('phase6a-readonly')
        log.logger.handlers=[logging.NullHandler()]
        stack.enter_context(patch.dict(sys.modules,{'src.utils.logger':log}))
        stack.enter_context(patch.dict(os.environ,{'DATABASE_PATH':str(database.resolve()),
            'ADMIN_SYNC_TOKEN':secrets.token_urlsafe(32),'ADMIN_SYNC_TOKEN_FILE':'',
            'XIAOZHI_MCP_ENDPOINT':'','XIAOZHI_MCP_TOKEN':'','AUTO_SYNC_ENABLED':'false','SYNC_SCHEDULE_ARMED':'false'}))
        stack.enter_context(patch('requests.sessions.Session.request',side_effect=AssertionError('Network forbidden')))
        stack.enter_context(patch('websockets.connect',side_effect=AssertionError('Cloud forbidden')))
        from src.storage.db import DatabaseManager,get_db
        from scripts.server_ops import inspect
        from fastapi.testclient import TestClient
        db=DatabaseManager.open_existing(database,read_only=True)
        before=inspect(database)
        appmod=importlib.import_module('src.api.app')
        stack.enter_context(patch.object(appmod,'get_db',return_value=db))
        stack.enter_context(patch('src.mcp.tools.get_db',return_value=db))
        app=appmod.create_app();app.dependency_overrides[get_db]=lambda:db
        client=stack.enter_context(TestClient(app))
        with db.get_connection() as conn:
            held=[dict(r) for r in conn.execute("SELECT p.id,p.url,p.title,p.content,a.visibility FROM pages p JOIN knowledge_access a ON p.id=a.page_id WHERE a.visibility!='public'")]
        held_urls = {row['url'] for row in held}
        for row in held:
            assert client.get('/page',params={'url':row['url']}).status_code==404
            response=client.post('/api/xiaozhi/tool',json={'tool':'wewin_get_page','arguments':{'url':row['url']}})
            assert response.json()['data'] is None
            response=client.get('/search',params={'q':row['title'],'limit':10})
            assert response.status_code == 200
            assert not held_urls.intersection(r['url'] for r in response.json()['results'])
            response=client.post('/api/xiaozhi/tool',json={'tool':'wewin_search','arguments':{'query':row['title'],'limit':20}})
            assert response.status_code == 200
            assert not held_urls.intersection(r['url'] for r in response.json()['results'])
            words=row['content'].split()
            if words:
                assert row['url'] not in {r['url'] for r in db.search(' '.join(words[:6]),10000)}
                assert row['url'] not in {r['url'] for r in db._fallback_like_search(words[:2],10000)}
        searches={}
        for query in ('Relative Clause','Oxford Phonics','tiếng Anh'):
            found=db.search(query,10000);assert found
            searches[query]=[r['url'] for r in found]
            assert client.get('/search',params={'q':query}).status_code==200
        with client.websocket_connect('/ws/mcp') as ws:
            calls=[('initialize',{}),('tools/list',{})]
            for row in held:
                calls.append(('tools/call',{'name':'wewin_get_page','arguments':{'url':row['url']}}))
                calls.append(('tools/call',{'name':'wewin_search','arguments':{'query':row['title'],'limit':20}}))
            for query in searches:calls.append(('tools/call',{'name':'wewin_search','arguments':{'query':query}}))
            for i,(method,params) in enumerate(calls):
                ws.send_json({'jsonrpc':'2.0','id':i,'method':method,'params':params})
                result=ws.receive_json();assert result['id']==i
                if method=='tools/list':
                    from src.mcp.tools import TOOL_DEFINITIONS
                    assert {t['name'] for t in result['result']['tools']}=={t['name'] for t in TOOL_DEFINITIONS}
                if method=='tools/call' and params['name']=='wewin_get_page':
                    assert result['result']['content'][0]['text'] == 'Không tìm thấy nội dung công khai được duyệt cho URL này trong kho WeWIN.'
                if method=='tools/call' and params['name']=='wewin_search':
                    text=result['result']['content'][0]['text']
                    # A held parent URL can prefix a distinct approved child page.
                    # Compare exact returned sources, rather than substring matches.
                    sources=set(re.findall(r'\(Nguồn: ([^)]+)\)',text))
                    assert not sources.intersection(held_urls)
        assert inspect(database)['fingerprints']==before['fingerprints']
        return {'status':'PASS','database_read_only':True,'external_network':False,'held_urls_tested':len(held),
                'public_searchable':before['public_searchable'],'sqlite_integrity':before['integrity'],
                'fts_consistent':before['fts']['consistent'],'search_urls':searches,
                'mcp_initialize_list_call':'PASS','rest_and_http_tools':'PASS','original_fingerprints_preserved':True}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--database',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args();result=verify(args.database)
    args.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k!='search_urls'}))
