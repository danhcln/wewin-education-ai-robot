"""Bounded real WebSocket probe using a copied SQLite database and fake token.

Starts only run_bridge.py and a broker bound to 127.0.0.1. No FastAPI process,
XiaoZhi Cloud, crawler, production secret, or scheduler is used. The result
records the actual OS; a Windows PASS is never a Linux runtime PASS.
"""
import argparse
import asyncio
from contextlib import suppress
import json
import os
from pathlib import Path
import platform
import secrets
import signal
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from websockets.asyncio.server import serve
from scripts.server_ops import backup, inspect
from scripts.rotate_admin_token import restrict_directory
from src.storage.db import DatabaseManager


async def probe(snapshot, directory):
    snapshot, directory = Path(snapshot).resolve(strict=True), Path(directory).resolve()
    if directory.exists() or directory.is_relative_to(ROOT / 'data') or directory.is_relative_to(ROOT / 'frontend'):
        raise ValueError('Use a new private probe directory outside production data and frontend')
    restrict_directory(directory)
    database = directory / 'probe.db'
    backup(snapshot, database)
    baseline = inspect(database)
    db = DatabaseManager.open_existing(database, read_only=True)
    with db.get_connection() as conn:
        held = [r[0] for r in conn.execute("SELECT p.url FROM pages p JOIN knowledge_access a ON a.page_id=p.id WHERE a.visibility!='public'")]
        public_article=conn.execute("SELECT url FROM public_pages WHERE length(content)>800 ORDER BY CASE WHEN url LIKE '%global-talent%' THEN 0 ELSE 1 END,id LIMIT 1").fetchone()[0]
    token = secrets.token_urlsafe(32)
    ready, finish = asyncio.Event(), asyncio.Event()
    accepted, closed, errors = [], [], []
    rpc_count = 0
    reading_state = {}

    async def broker(ws):
        nonlocal rpc_count
        accepted.append(time.monotonic())
        number = len(accepted)
        try:
            assert ws.request.headers.get('Authorization') == 'Bearer ' + token
            assert parse_qs(urlsplit(ws.request.path).query).get('token') == [token]

            async def rpc(method, params=None):
                nonlocal rpc_count
                rpc_count += 1
                msg_id = rpc_count
                await ws.send(json.dumps({'jsonrpc':'2.0','id':msg_id,'method':method,'params':params or {}}))
                reply = json.loads(await asyncio.wait_for(ws.recv(), timeout=10))
                assert reply['id'] == msg_id and 'result' in reply
                return reply['result']

            result = await rpc('initialize')
            assert result['capabilities']['tools'] is not None
            await ws.send('{invalid-json-' + token)
            result = await rpc('tools/list')
            from src.mcp.tools import TOOL_DEFINITIONS
            assert {t['name'] for t in result['tools']} == {t['name'] for t in TOOL_DEFINITIONS}
            result = await rpc('tools/call', {'name':'wewin_test_connection','arguments':{}})
            assert result['content'][0]['text'] == 'WeWIN MCP OK'
            for url in held:
                result = await rpc('tools/call', {'name':'wewin_get_page','arguments':{'url':url}})
                assert result['content'][0]['text'] == 'Không tìm thấy nội dung công khai được duyệt cho URL này trong kho WeWIN.'
                result=await rpc('tools/call',{'name':'wewin_read_article','arguments':{'url':url}})
                assert json.loads(result['content'][0]['text'])['status']=='not_found'
            result = await rpc('tools/call', {'name':'wewin_search','arguments':{'query':'Oxford Phonics','limit':3}})
            assert 'bo-sach-day-phat-am-tieng-anh-oxford-phonics-world' in result['content'][0]['text']
            if number==1:
                result=await rpc('tools/call',{'name':'wewin_read_article','arguments':{'url':public_article,'chunk_chars':200}})
                reading_state.update(json.loads(result['content'][0]['text']))
                assert reading_state['part']==1 and reading_state['has_more'] and len(reading_state['text'])<=200
                result=await rpc('tools/call',{'name':'wewin_read_article','arguments':{'url':public_article,'mode':'summary'}})
                assert len(json.loads(result['content'][0]['text'])['text'])<=900
            elif number==2:
                result=await rpc('tools/call',{'name':'wewin_continue_reading','arguments':{
                    'reading_id':reading_state['reading_id'],'part':reading_state['next_part']}})
                part=json.loads(result['content'][0]['text']);assert part['part']==2
                result=await rpc('tools/call',{'name':'wewin_stop_reading','arguments':{'reading_id':reading_state['reading_id']}})
                assert json.loads(result['content'][0]['text'])['status']=='stopped'
                result=await rpc('tools/call',{'name':'wewin_continue_reading','arguments':{'reading_id':reading_state['reading_id'],'part':3}})
                assert json.loads(result['content'][0]['text'])['status']=='reading_not_found'
            await rpc('ping')
            if number == 1:
                closed.append(time.monotonic())
                await ws.close(code=1012, reason='fixture restart ' + token)
            elif number == 2:
                ready.set()
                await finish.wait()
            else:
                raise AssertionError('Unexpected extra reconnect')
        except Exception as error:
            errors.append(type(error).__name__)
            ready.set()

    process = None
    log_path = directory / 'bridge-output.log'
    status_path = directory / 'bridge-status.json'
    started_at = time.monotonic()
    log_stream = log_path.open('wb')
    try:
        async with serve(broker, '127.0.0.1', 0, max_size=1024*1024) as server:
            port = server.sockets[0].getsockname()[1]
            child_env = {**os.environ,
                'DATABASE_PATH':str(database), 'KNOWLEDGE_JSON_PATH':str(directory/'unused.json'),
                'XIAOZHI_MCP_ENDPOINT':f'ws://127.0.0.1:{port}/mcp/', 'XIAOZHI_MCP_ENDPOINT_FILE':'',
                'XIAOZHI_MCP_TOKEN':token, 'XIAOZHI_MCP_TOKEN_FILE':'',
                'ADMIN_SYNC_TOKEN':secrets.token_urlsafe(32), 'ADMIN_SYNC_TOKEN_FILE':'',
                'BRIDGE_STATUS_PATH':str(status_path), 'AUTO_SYNC_ENABLED':'false',
                'SYNC_SCHEDULE_ARMED':'false', 'SYNC_SCHEDULER_OWNER':'external', 'DEBUG':'false',
                'PYTHONUNBUFFERED':'1', 'PYTHONDONTWRITEBYTECODE':'1'}
            options = {'creationflags':subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {}
            process = subprocess.Popen([sys.executable,'-B',str(ROOT/'run_bridge.py')],
                cwd=directory, env=child_env, stdout=log_stream, stderr=subprocess.STDOUT, **options)
            await asyncio.wait_for(ready.wait(), timeout=35)
            assert not errors, 'Local broker protocol failed: ' + ','.join(errors)
            assert len(accepted) == 2 and process.poll() is None
            reconnect_gap = accepted[1] - closed[0]
            assert reconnect_gap >= 2, 'Reconnect skipped its real backoff'
            state = json.loads(status_path.read_text(encoding='utf-8'))
            assert state['state'] == 'connected' and state['pid'] == process.pid
            # Exercise stale PID handling after a crash of this fixture process only.
            process.kill()
            await asyncio.to_thread(process.wait, 5)
            from src.mcp.bridge_status import read_status
            with patch.dict(os.environ, {'BRIDGE_STATUS_PATH':str(status_path)}):
                assert read_status() == 'not_connected'
            finish.set()
    finally:
        finish.set()
        if process is not None and process.poll() is None:
            process.kill()
            with suppress(subprocess.TimeoutExpired):
                await asyncio.to_thread(process.wait, 5)
        log_stream.close()
    logs = b'\n'.join(path.read_bytes() for path in [log_path, *sorted((directory/'logs').glob('*.log'))])
    assert token.encode() not in logs, 'Fixture credential was echoed in a log'
    assert inspect(database)['fingerprints'] == baseline['fingerprints']
    result = {'status':'PASS','host_os':platform.system(),'python':platform.python_version(),
              'linux_runtime_pass':platform.system()=='Linux','broker':'loopback_fixture',
              'production_cloud_connected':False,'fastapi_required':False,
              'connections':len(accepted),'rpc_count':rpc_count,'held_urls_checked':len(held),
              'reconnect_gap_seconds':reconnect_gap,'malformed_json_recovery':'PASS',
              'fake_credential_redaction':'PASS','dead_process_status':'PASS',
              'reading_protocol':'PASS','reading_state_after_reconnect':'PASS','public_article_checked':public_article,
              'copied_database_unchanged':True,'elapsed_seconds':round(time.monotonic()-started_at,3)}
    (directory/'result.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', required=True, type=Path)
    parser.add_argument('--directory', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(asyncio.run(probe(args.snapshot, args.directory))))
