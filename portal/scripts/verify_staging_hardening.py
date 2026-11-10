"""Read-only final protection audit for the new run; no baseline overwrite."""
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import httpx

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ai_server.runtime import source_fingerprint


def rows(db,name):return sorted(db.execute('SELECT * FROM "'+name+'"').fetchall(),key=repr)


if __name__=='__main__':
    out=ROOT/'artifacts/staging-hardening';backup=out/'restart-backup'
    original=json.loads((backup/'protected.json').read_text());changed=[name for name,digest in original.items() if hashlib.sha256(Path(name).read_bytes()).hexdigest()!=digest]
    business={}
    with sqlite3.connect((ROOT/'data/education.sqlite3').as_uri()+'?mode=ro',uri=True) as now,sqlite3.connect((backup/'portal-before.sqlite3').as_uri()+'?mode=ro',uri=True) as old:
        for (name,) in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            if name not in ('sessions','audit'):business[name]=rows(now,name)==rows(old,name)
        integrity=now.execute('PRAGMA integrity_check').fetchone()[0];fk=len(now.execute('PRAGMA foreign_key_check').fetchall());links=now.execute('SELECT COUNT(*) FROM self_hosted_links WHERE enabled=1').fetchone()[0]
    with sqlite3.connect((ROOT/'data/ai-staging.sqlite3').as_uri()+'?mode=ro',uri=True) as now,sqlite3.connect((backup/'ai-before.sqlite3').as_uri()+'?mode=ro',uri=True) as old:
        ids=[r[0] for r in old.execute('SELECT id FROM agents')]
        agents_unchanged=all(now.execute('SELECT * FROM agents WHERE id=?',(i,)).fetchone()==old.execute('SELECT * FROM agents WHERE id=?',(i,)).fetchone() for i in ids)
        new_ids=[r[0] for r in now.execute('SELECT id FROM agents') if r[0] not in ids]
        assert all(i.startswith('qa_hardening_') for i in new_ids)
    manifest=json.loads((backup/'launch-manifest.json').read_text());key=Path(manifest['key_file']).read_text().strip()
    key_unchanged=hashlib.sha256(Path(manifest['key_file']).read_bytes()).hexdigest()==manifest['key_sha256']
    with httpx.Client(trust_env=False,timeout=10) as client:
        health=client.get('http://127.0.0.1:8010/health').json()
        runtime=client.get('http://127.0.0.1:8010/v1/runtime',headers={'Authorization':'Bearer '+key}).json()
        portal=client.get('http://127.0.0.1:8001/health').status_code
        models=client.get('http://127.0.0.1:11434/api/tags').json()
    leaks=[]
    known=[key.encode(),(ROOT.parent/'Wewin Connector/Wewin_AI_Connector/.secrets/admin_sync_token').read_bytes().strip(),(out/'qa/admin-key').read_bytes().strip()]
    for folder in ('ai_server','scripts','docs','frontend/src','frontend/dist'):
        for path in (ROOT/folder).rglob('*'):
            if path.is_file() and path.suffix in ('.py','.md','.json','.ts','.tsx','.js','.css','.html') and any(secret and secret in path.read_bytes() for secret in known):leaks.append(str(path.relative_to(ROOT)))
    result={'protected_total':len(original),'protected_changed':changed,'main_business_tables_unchanged':all(business.values()),'main_changed_tables':[n for n,v in business.items() if not v],'main_integrity':integrity,'foreign_key_violations':fk,'main_enabled_staging_links':links,'old_ai_agents_unchanged':agents_unchanged,'old_ai_agent_count':len(ids),'owned_test_agents_added':new_ids,'key_unchanged':key_unchanged,'health':health,'runtime':runtime,'source_hash_matches_current_checkout':health['build']['ai_source_sha256']==source_fingerprint(),'portal_http':portal,'original_ollama_models':models,'secret_leaks':leaks,'physical_changes':False}
    (out/'protection-final.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('runtime','original_ollama_models')},indent=2))
    assert not changed and all(business.values()) and integrity=='ok' and fk==0 and links==0 and agents_unchanged and key_unchanged and not leaks and result['source_hash_matches_current_checkout'] and portal==200 and health['physical_connections']==0 and not health['real_device_enrollment_enabled']
