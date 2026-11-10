"""Old code + copied DB on 8012; never stops or writes the live 8010 runtime.

Checks module origin, old Agent readback and real readonly MCP stdio. Uses the
base interpreter directly (not a Windows venv redirector) so the owned Popen
handle is the server PID that is terminated in finally.
"""
import hashlib
import argparse
import json
import os
from pathlib import Path
import socket
import sqlite3
import subprocess
import sys
import time
import httpx

ROOT=Path(__file__).resolve().parents[1]


if __name__=='__main__':
    base=ROOT/'artifacts/staging-hardening';backup=base/'restart-backup'
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,default=base/'rollback-rehearsal');parser.add_argument('--backup',type=Path,default=backup);args=parser.parse_args();out=args.out.resolve();backup=args.backup.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):raise ValueError('Rehearsal data must remain in artifacts/')
    if not backup.is_relative_to(ROOT/'artifacts'):raise ValueError('Backup must remain inside artifacts/')
    out.mkdir(parents=True,exist_ok=True)
    manifest=json.loads((backup/'launch-manifest.json').read_text());source=Path(manifest['rollback_code'])
    policy=ROOT.parent/'Wewin Connector/Wewin_AI_Connector/src/storage/knowledge_policy.py'
    target=backup/'Wewin Connector/Wewin_AI_Connector/src/storage/knowledge_policy.py'
    content=policy.read_bytes();digest=hashlib.sha256(content).hexdigest()
    if target.exists() and target.read_bytes()!=content:raise ValueError('Existing recovery dependency mismatch')
    if not target.exists():target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(content)
    receipt=backup/'rollback-dependency-receipt.json'
    if not receipt.exists():receipt.write_text(json.dumps({'knowledge_policy_sha256':digest,'scope':'Pure source policy only; no Connector runtime, key or database copied'},indent=2))
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1',8012))==0:raise RuntimeError('8012 occupied; nothing stopped')
    copied=out/'ai-copy.sqlite3'
    if copied.exists():raise FileExistsError('Do not overwrite recovery rehearsal DB')
    with sqlite3.connect((backup/'ai-before.sqlite3').as_uri()+'?mode=ro',uri=True) as old,sqlite3.connect(copied) as new:old.backup(new)
    env={**os.environ,'PYTHONPATH':str(source)+os.pathsep+str(ROOT/'.venv-ai/Lib/site-packages'),'PYTHONNOUSERSITE':'1','PYTHONIOENCODING':'utf-8','WEWIN_AI_DB':str(copied),'WEWIN_AI_ADMIN_KEY_FILE':str(backup/'ai-admin-key'),'WEWIN_AI_OLLAMA':manifest['ollama'],'WEWIN_AI_ASR_MODEL':manifest['asr_model'],'WEWIN_AI_TTS_MODELS':manifest['tts_models'],'WEWIN_AI_CONNECTOR_DB':manifest['connector_db'],'WEWIN_AI_OPUS_DIR':manifest['opus_dir'],'WEWIN_AI_PUBLIC_WS':'ws://127.0.0.1:8012/xiaozhi/v1/','WEWIN_AI_ALLOW_REAL_DEVICES':'0'}
    python=sys._base_executable
    module=subprocess.check_output([python,'-c','import ai_server.app;print(ai_server.app.__file__)'],cwd=source,env=env,text=True).strip()
    assert Path(module).resolve()==source/'ai_server/app.py'
    with (out/'server.log').open('w') as log:
        child=subprocess.Popen([python,'-m','uvicorn','ai_server.app:app','--host','127.0.0.1','--port','8012','--no-access-log'],cwd=source,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            with httpx.Client(base_url='http://127.0.0.1:8012',headers={'Authorization':'Bearer '+(backup/'ai-admin-key').read_text().strip()},timeout=120,trust_env=False) as client:
                for _ in range(60):
                    if child.poll() is not None:raise RuntimeError('Owned rehearsal process exited')
                    try:
                        health=client.get('/health').json();break
                    except httpx.ConnectError:time.sleep(.25)
                else:raise RuntimeError('Rehearsal startup timeout')
                assert health['service']=='wewin-ai-staging' and not health['real_device_enrollment_enabled']
                agent=manifest['agents_before'][0];read=client.get('/v1/agents/'+agent['id']);read.raise_for_status();read=read.json()
                assert read['revision']==agent['revision'] and read['config_hash']==agent['hash'] and read['loaded']
            requests=[{'jsonrpc':'2.0','id':1,'method':'initialize','params':{}},{'jsonrpc':'2.0','id':2,'method':'tools/call','params':{'name':'wewin_get_programs','arguments':{}}}]
            mcp=subprocess.run([python,'-m','ai_server.mcp_server'],cwd=source,env=env,input='\n'.join(json.dumps(r) for r in requests)+'\n',capture_output=True,text=True,encoding='utf-8',timeout=15)
            if mcp.returncode:
                (out/'mcp-error.log').write_text(mcp.stderr,encoding='utf-8');mcp.check_returncode()
            answers=[json.loads(line) for line in mcp.stdout.splitlines()];assert all('result' in a and 'error' not in a for a in answers)
            assert 'Cambridge' in answers[-1]['result']['content'][0]['text']
            result={'rehearsal':'PASS','live_fault_injection':False,'live_8010_untouched':True,'origin':'http://127.0.0.1:8012','old_module_path':module,'old_commit':manifest['rollback_commit'],'agent_revision':read['revision'],'agent_hash_matches_backup':True,'readonly_mcp_programs':'PASS','policy_sha256':digest,'physical_enrollment':False,'owned_pid':child.pid}
            (out/'results.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result),flush=True)
        finally:
            child.terminate();child.wait(timeout=20)
