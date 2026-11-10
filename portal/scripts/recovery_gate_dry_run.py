"""Security-compatible source archive + QA DB/issuer restore on loopback8012.
Never stops live services, writes main DB, contacts a robot or restores Cloud.
"""
import hashlib
import io
import json
import os
from pathlib import Path
import socket
import sqlite3
from contextlib import closing
import subprocess
import sys
import tarfile
import time
from uuid import uuid4
import httpx

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'artifacts/real-connection-gate'


if __name__=='__main__':
    with socket.socket() as probe:
        if probe.connect_ex(('127.0.0.1',8012))==0:raise RuntimeError('8012 occupied; nothing stopped')
    key=(BASE/'qa/admin-key').read_text().strip()
    with httpx.Client(base_url='http://127.0.0.1:8011',headers={'Authorization':'Bearer '+key},trust_env=False) as client:
        health=client.get('/health').json();assert not health['active_connections'] and not health['real_device_enrollment_enabled']
    if subprocess.check_output(['git','status','--porcelain','--','ai_server'],cwd=ROOT):raise RuntimeError('Commit tested AI source before recovery rehearsal')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    out=BASE/('recovery-'+uuid4().hex[:8]);out.mkdir()
    source=out/'wewin_education_portal';source.mkdir()
    archive=subprocess.check_output(['git','archive',commit,'ai_server'],cwd=ROOT)
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:bundle.extractall(source,filter='data')
    policy=ROOT.parent/'Wewin Connector/Wewin_AI_Connector/src/storage/knowledge_policy.py';policy_copy=out/'Wewin Connector/Wewin_AI_Connector/src/storage/knowledge_policy.py'
    policy_copy.parent.mkdir(parents=True);policy_copy.write_bytes(policy.read_bytes())
    with closing(sqlite3.connect((BASE/'qa/ai.sqlite3').as_uri()+'?mode=ro',uri=True)) as current,closing(sqlite3.connect(out/'restored.sqlite3')) as restored:current.backup(restored)
    for name in ('admin-key','ai_device_issuer_key'):(out/name).write_bytes((BASE/'qa'/name).read_bytes())
    with closing(sqlite3.connect(out/'restored.sqlite3')) as db:
        agents=list(db.execute('SELECT id,revision,hash FROM agents ORDER BY id'))
        managed=list(db.execute('SELECT m.device_id,m.owner_id,m.tenant_id,m.binding_version,d.revoked,p.requires_tls,p.device_origin FROM managed_devices m JOIN devices d ON d.id=m.device_id JOIN device_transport_policy p ON p.device_id=m.device_id'))
        assert managed and all(r[4] for r in managed),'Only latest fully revoked QA snapshot is eligible; never revive stale credentials'
    env={**os.environ,'PYTHONPATH':str(source)+os.pathsep+str(ROOT/'.venv-ai/Lib/site-packages'),'PYTHONNOUSERSITE':'1','PYTHONIOENCODING':'utf-8','WEWIN_AI_DB':str(out/'restored.sqlite3'),'WEWIN_AI_ADMIN_KEY_FILE':str(out/'admin-key'),'WEWIN_AI_DEVICE_ISSUER_KEY_FILE':str(out/'ai_device_issuer_key'),'WEWIN_AI_ALLOW_REAL_DEVICES':'0','WEWIN_AI_DEVICE_ORIGIN':'https://192.168.2.10:8014','WEWIN_AI_TRUST_TLS_EDGE':'1','WEWIN_AI_CONNECTOR_DB':str(ROOT.parent/'Wewin Connector/Wewin_AI_Connector/data/wewin_fts.db')}
    with (out/'server.log').open('w') as log:
        child=subprocess.Popen([sys._base_executable,'-m','uvicorn','ai_server.app:app','--host','127.0.0.1','--port','8012','--no-access-log'],cwd=source,env=env,stdout=log,stderr=log,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            with httpx.Client(base_url='http://127.0.0.1:8012',headers={'Authorization':'Bearer '+key},trust_env=False,timeout=10) as client:
                for _ in range(80):
                    if child.poll() is not None:raise RuntimeError('Owned recovery process exited')
                    try:restored_health=client.get('/health').json();break
                    except httpx.ConnectError:time.sleep(.25)
                else:raise RuntimeError('Recovery startup timed out')
                for agent,revision,digest in agents:
                    r=client.get('/v1/agents/'+agent);r.raise_for_status();actual=r.json();assert actual['revision']==revision and actual['config_hash']==digest and actual['loaded']
                for device,owner,tenant,version,revoked,requires_tls,pinned_origin in managed:
                    r=client.get('/v1/devices/'+device+'/diagnostics',headers={'X-WeWIN-Owner':owner,'X-WeWIN-Tenant':tenant});r.raise_for_status();actual=r.json();assert actual['revoked']==revoked and actual['binding_version']==version and not actual['online']
                    assert actual['transport_policy']=={'requires_tls':requires_tls,'device_origin':pinned_origin}
                    assert client.get('/v1/devices/'+device+'/diagnostics',headers={'X-WeWIN-Owner':'wrong','X-WeWIN-Tenant':tenant}).status_code==403
                assert not restored_health['real_device_enrollment_enabled'] and not restored_health['active_connections']
            result={'result':'PASS','source_commit':commit,'archive_sha256':hashlib.sha256(archive).hexdigest(),'restored_origin':'http://127.0.0.1:8012','restored_agents':len(agents),'managed_revoked_devices_preserved':len(managed),'issuer_generation_exact':(out/'ai_device_issuer_key').read_bytes()==(BASE/'qa/ai_device_issuer_key').read_bytes(),'owner_tenant_binding_readback':True,'tls_pins_preserved':True,'live_services_stopped':False,'cloud_rollback_tested':False,'physical_recovery_tested':False,'scope':'latest revoked QA snapshot only; stale/unknown revocation ledger is NO-GO'}
            (out/'results.json').write_text(json.dumps(result,indent=2));(BASE/'recovery-results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result))
        finally:child.terminate();child.wait(timeout=20)
