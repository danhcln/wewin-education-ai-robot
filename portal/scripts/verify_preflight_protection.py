"""Compare protected files and business tables with this run's baseline.

Normal main-Portal login/logout audit/session writes are excluded from business
table comparisons, not hidden as an unchanged entire database claim.
"""
import hashlib
import json
from pathlib import Path
import sqlite3
import httpx
from capture_preflight_baseline import ROOT,OUT,hashes


def table_hash(db,name):
    rows=db.execute('SELECT * FROM "'+name+'"').fetchall()
    encoded=json.dumps(sorted(rows,key=repr),ensure_ascii=False,default=repr).encode()
    return {'rows':len(rows),'sha256':hashlib.sha256(encoded).hexdigest()}


if __name__=='__main__':
    before=json.loads((OUT/'protected-before.json').read_text());after=hashes()
    unchanged=[p for p in before if before[p]==after[p]];changed=[p for p in before if before[p]!=after[p]]
    tables={}
    with sqlite3.connect((ROOT/'data/education.sqlite3').as_uri()+'?mode=ro',uri=True) as current,sqlite3.connect((OUT/'education-before.sqlite3').as_uri()+'?mode=ro',uri=True) as old:
        for (name,) in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            if name in ('sessions','audit'):continue
            previous=table_hash(old,name);now=table_hash(current,name)
            tables[name]={'unchanged':previous==now,'rows':now['rows']}
        integrity=current.execute('PRAGMA integrity_check').fetchone()[0]
        violations=len(current.execute('PRAGMA foreign_key_check').fetchall())
        links=current.execute('SELECT COUNT(*) FROM self_hosted_links WHERE enabled=1').fetchone()[0]
    with httpx.Client(trust_env=False) as client:
        health={str(port):client.get(f'http://127.0.0.1:{port}/health').status_code for port in (8001,8010)}
    secrets=[]
    for p in (ROOT/'.secrets/ai_admin_key',ROOT.parent/'Wewin Connector/Wewin_AI_Connector/.secrets/admin_sync_token',OUT/'admin-key'):
        if p.is_file():secrets.append(p.read_bytes().strip())
    leaks=[]
    candidates=[p for folder in ('ai_server','scripts','docs','frontend/src','frontend/dist') for p in (ROOT/folder).rglob('*') if p.is_file() and p.suffix in ('.py','.md','.json','.ts','.tsx','.js','.css','.html')]
    for path in candidates:
        if any(secret and secret in path.read_bytes() for secret in secrets):leaks.append(str(path.relative_to(ROOT)))
    result={'protected_unchanged':len(unchanged),'protected_total':len(before),'protected_changed':changed,'main_business_tables':tables,'main_integrity':integrity,'foreign_key_violations':violations,'main_enabled_staging_links':links,'live_health_http':health,'secret_leaks':leaks,'normal_login_logout_session_audit_writes':True,'physical_changes_performed':False}
    (OUT/'protection-after.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    assert not changed and all(t['unchanged'] for t in tables.values()) and integrity=='ok' and violations==0 and links==0 and not leaks
