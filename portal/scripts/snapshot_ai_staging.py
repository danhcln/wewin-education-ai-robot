"""Read-only pre-restart evidence + SQLite backups. Refuses to overwrite a run.

Does not stop anything. Default key authentication and Agent hashes must agree
with the default database before that launch configuration is considered proven.
"""
import hashlib
import argparse
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import httpx

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ai_server.settings import Settings


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,default=ROOT/'artifacts/staging-hardening/restart-backup');args=parser.parse_args()
    out=args.out.resolve()
    if not out.is_relative_to(ROOT/'artifacts'):raise ValueError('Snapshot must remain inside ignored artifacts/')
    if out.exists():raise FileExistsError('Do not overwrite the restart baseline')
    settings=Settings();key=settings.admin_key()
    with httpx.Client(base_url='http://127.0.0.1:8010',headers={'Authorization':'Bearer '+key},timeout=10,trust_env=False) as client:
        health=client.get('/health');health.raise_for_status();health=health.json()
        if health['service']!='wewin-ai-staging' or health['active_connections'] or health['real_device_enrollment_enabled']:raise RuntimeError('Not an idle, physical-disabled staging process')
        response=client.get('/v1/agents');response.raise_for_status();agents=response.json()['items']
    with sqlite3.connect(settings.db.resolve().as_uri()+'?mode=ro',uri=True) as source:
        rows={r[0]:(r[1],r[2]) for r in source.execute('SELECT id,revision,hash FROM agents')}
        assert rows=={r['id']:(r['revision'],r['hash']) for r in agents},'API is not using the expected database'
        assert source.execute('SELECT COUNT(*) FROM devices WHERE kind="physical"').fetchone()[0]==0
        out.mkdir(parents=True)
        with sqlite3.connect(out/'ai-before.sqlite3') as destination:source.backup(destination)
    with sqlite3.connect((ROOT/'data/education.sqlite3').as_uri()+'?mode=ro',uri=True) as source,sqlite3.connect(out/'portal-before.sqlite3') as destination:
        assert source.execute('SELECT COUNT(*) FROM self_hosted_links WHERE enabled=1').fetchone()[0]==0
        source.backup(destination)
    protected=json.loads((ROOT/'artifacts/connection-preflight/protected-before.json').read_text())
    hashes={name:hashlib.sha256(Path(name).read_bytes()).hexdigest() for name in protected}
    (out/'protected.json').write_text(json.dumps(hashes,indent=2))
    # Private copy stays in ignored artifacts, never output or checked into Git.
    (out/'ai-admin-key').write_bytes(settings.key_file.read_bytes())
    issuer=settings.device_issuer_file
    if issuer.exists():(out/'ai-device-issuer-key').write_bytes(issuer.read_bytes())
    subprocess.run([sys.executable,'-m','pip','freeze'],stdout=(out/'dependencies.txt').open('w'),check=True)
    rollback=out/'rollback-source';rollback.mkdir()
    # Read a known previous commit, without resetting the active checkout.
    rollback_commit=health['build']['git_commit']
    # A source rollback to a pre-ownership service is unsafe after enrollment.
    with sqlite3.connect(settings.db.resolve().as_uri()+'?mode=ro',uri=True) as source:
        managed=source.execute("SELECT 1 FROM sqlite_master WHERE name='managed_devices'").fetchone()
        if managed and source.execute('SELECT COUNT(*) FROM managed_devices').fetchone()[0]:raise RuntimeError('Managed enrollment exists: use the security-compatible recovery runbook, not legacy automatic source rollback')
    archive=subprocess.run(['git','archive',rollback_commit,'ai_server'],cwd=ROOT,capture_output=True,check=True)
    (out/'rollback-source.tar').write_bytes(archive.stdout)
    import tarfile
    with tarfile.open(out/'rollback-source.tar') as bundle:bundle.extractall(rollback,filter='data')
    # Old MCP resolves this pure policy relative to its checkout, not DB path.
    policy=ROOT.parent/'Wewin Connector/Wewin_AI_Connector/src/storage/knowledge_policy.py'
    policy_copy=out/'Wewin Connector/Wewin_AI_Connector/src/storage/knowledge_policy.py'
    policy_copy.parent.mkdir(parents=True,exist_ok=True);policy_copy.write_bytes(policy.read_bytes())
    (out/'rollback-dependency-receipt.json').write_text(json.dumps({'knowledge_policy_sha256':hashlib.sha256(policy.read_bytes()).hexdigest(),'scope':'Pure source policy only; no Connector runtime, key or database copied'},indent=2))
    manifest={'origin':'http://127.0.0.1:8010','python':str(ROOT/'.venv-ai/Scripts/python.exe'),'root':str(ROOT),'rollback_code':str(rollback),'rollback_commit':rollback_commit,'database':str(settings.db.resolve()),'key_file':str(settings.key_file.resolve()),'key_sha256':hashlib.sha256(settings.key_file.read_bytes()).hexdigest(),'ollama':settings.ollama,'asr_model':settings.asr_model,'tts_models':settings.tts_models,'connector_db':str(settings.connector_db.resolve()),'opus_dir':str(ROOT.parent/'references/xiaozhi/python-client/libs/libopus/win/x64'),'public_ws':settings.public_ws,'physical_enrollment':False,'health_before':health,'agents_before':agents}
    (out/'launch-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(json.dumps({'backup':str(out),'agents_preserved':len(agents),'physical_devices':0,'active_connections':0,'default_database_verified_against_api':True}))
