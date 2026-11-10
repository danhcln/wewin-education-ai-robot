"""Verify this migration's own fresh baseline, not an older task's snapshot."""
import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess

ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'artifacts/independent-migration'


def rows(db,table):return sorted([list(r) for r in db.execute('SELECT * FROM "'+table+'"')],key=lambda row:json.dumps(row,default=str))


if __name__=='__main__':
    protected=json.loads((OUT/'protected-before.json').read_text())
    changed=[p for p,digest in protected.items() if not Path(p).is_file() or hashlib.sha256(Path(p).read_bytes()).hexdigest()!=digest]
    compared={}
    with sqlite3.connect((OUT/'portal-before.sqlite3').as_uri()+'?mode=ro',uri=True) as before,sqlite3.connect((ROOT/'data/education.sqlite3').as_uri()+'?mode=ro',uri=True) as current:
        for (name,) in before.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            if name in ('sessions','audit','schema_version'):continue
            compared[name]=rows(before,name)==rows(current,name)
        integrity=current.execute('PRAGMA integrity_check').fetchone()[0];fk=current.execute('PRAGMA foreign_key_check').fetchall()
    with sqlite3.connect((OUT/'ai-before.sqlite3').as_uri()+'?mode=ro',uri=True) as before,sqlite3.connect((ROOT/'data/ai-staging.sqlite3').as_uri()+'?mode=ro',uri=True) as current:
        old={r[0]:list(r) for r in before.execute('SELECT * FROM agents')};now={r[0]:list(r) for r in current.execute('SELECT * FROM agents')}
        agents_preserved=all(now.get(k)==v for k,v in old.items())
        ai_integrity=current.execute('PRAGMA integrity_check').fetchone()[0];ai_fk=current.execute('PRAGMA foreign_key_check').fetchall()
    tracked=subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).split(b'\0')
    key_paths=[ROOT/'.secrets/ai_admin_key',ROOT/'.secrets/ai_device_issuer_key',OUT/'qa/admin-key',OUT/'qa/ai_device_issuer_key',ROOT.parent/'Wewin Connector/Wewin_AI_Connector/.secrets/admin_sync_token']
    secrets=[p.read_bytes().strip() for p in key_paths if p.is_file()]
    files=[ROOT/p.decode() for p in tracked if p]+[p for p in (ROOT/'frontend/dist').rglob('*') if p.is_file()]
    leaks=[str(p.relative_to(ROOT)) for p in files if p.is_file() and any(secret and secret in p.read_bytes() for secret in secrets)]
    result={'protected_files_unchanged':len(protected)-len(changed),'protected_total':len(protected),'protected_changed':changed,'portal_business_tables_unchanged':compared,'portal_integrity':integrity,'portal_foreign_keys':fk,'baseline_agent_count':len(old),'baseline_agents_preserved':agents_preserved,'ai_integrity':ai_integrity,'ai_foreign_keys':ai_fk,'secret_leaks_in_tracked_or_built_files':leaks,'normal_login_audit_and_additive_migrations_allowed':True,'physical_changes_performed':False}
    (OUT/'protection-after.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    assert not changed and all(compared.values()) and integrity==ai_integrity=='ok' and not fk and not ai_fk and agents_preserved and not leaks
