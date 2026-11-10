"""Minimal MCP stdio tools service: public read-only WeWIN knowledge only.

It does not start or alter the existing XiaoZhi MCP Bridge. No media/device writes.
"""
import json
import re
import sqlite3
import sys
import importlib.util
from contextlib import closing
from .settings import Settings,ROOT

TOOLS=[
    {'name':'wewin_test_connection','description':'Check the WeWIN knowledge MCP connection.','inputSchema':{'type':'object','properties':{}}},
    {'name':'wewin_search','description':'Search verified public WeWIN pages before answering questions about WeWIN.','inputSchema':{'type':'object','properties':{'query':{'type':'string'}},'required':['query']}},
    {'name':'wewin_get_programs','description':'Read public WeWIN course information; do not invent courses or fees.','inputSchema':{'type':'object','properties':{}}},
]


def public_search(settings,query):
    terms=re.findall(r'\w+',str(query)[:300])[:12]
    if not terms:return []
    match=' OR '.join('"'+t+'"' for t in terms)
    # Reuse the reviewed canonical pure policy without importing DatabaseManager,
    # whose package initializer can pull in crawler/runtime initialization.
    _policy_candidates = [
        ROOT.parent / 'connector/src/storage/knowledge_policy.py',
        ROOT.parent / 'Wewin Connector/Wewin_AI_Connector/src/storage/knowledge_policy.py',
    ]
    policy_file = next((p for p in _policy_candidates if p.exists()), _policy_candidates[0])
    spec=importlib.util.spec_from_file_location('wewin_publication_policy',policy_file)
    policy=importlib.util.module_from_spec(spec);spec.loader.exec_module(policy)
    with closing(sqlite3.connect(settings.connector_db.resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.row_factory=sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        try:protected={r[0] for r in db.execute('SELECT content_hash FROM protected_knowledge')}
        except sqlite3.OperationalError:protected=set()
        db.create_function('knowledge_is_public',3,lambda url,title,body:int(policy.classify(url,title,body,protected)[0]=='public'))
        rows=db.execute('SELECT p.title,p.url,p.content FROM public_pages p JOIN pages_fts f ON f.rowid=p.id WHERE pages_fts MATCH ? LIMIT 4',(match,)).fetchall()
    return [dict(row,content=row['content'][:1400]) for row in rows if policy.classify(row['url'],row['title'],row['content'],protected)[0]=='public']


def dispatch(request,settings):
    method=request.get('method');params=request.get('params') or {}
    if method=='initialize':
        return {'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'wewin-public-knowledge','version':'1.0.0'}}
    if method=='tools/list':return {'tools':TOOLS}
    if method=='tools/call':
        name=params.get('name');args=params.get('arguments') or {}
        if name=='wewin_test_connection':result={'status':'WeWIN MCP OK','scope':'public_read_only'}
        elif name=='wewin_search':result={'items':public_search(settings,args.get('query',''))}
        elif name=='wewin_get_programs':result={'items':public_search(settings,'khóa học Cambridge IELTS mầm non')}
        else:raise ValueError('Tool not permitted')
        return {'content':[{'type':'text','text':json.dumps(result,ensure_ascii=False)}],'isError':False}
    if method=='ping':return {}
    raise ValueError('Unsupported MCP method')


def main():
    settings=Settings()
    for line in sys.stdin:
        if len(line)>16384:return
        request={}
        try:
            request=json.loads(line)
            if 'id' not in request:continue
            result={'jsonrpc':'2.0','id':request['id'],'result':dispatch(request,settings)}
        except Exception:
            result={'jsonrpc':'2.0','id':request.get('id'),'error':{'code':-32602,'message':'MCP request failed; public read-only tool unavailable'}}
        print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
