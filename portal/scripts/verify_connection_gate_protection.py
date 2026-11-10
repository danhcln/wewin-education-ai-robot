"""This gate's fresh baseline. Existing rows/keys stay intact; QA additions allowed."""
from collections import Counter
from contextlib import closing
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import httpx

ROOT=Path(__file__).resolve().parents[1];BASE=ROOT/'artifacts/real-connection-gate'
sys.path.insert(0,str(ROOT))
from ai_server.runtime import source_fingerprint


def compare(before_path,current_path,append_only=False):
    checks={}
    with closing(sqlite3.connect(before_path.as_uri()+'?mode=ro',uri=True)) as old,closing(sqlite3.connect(current_path.as_uri()+'?mode=ro',uri=True)) as current:
        for (table,) in old.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"):
            if not append_only and table in ('audit','sessions'):continue
            before=Counter(tuple(r) for r in old.execute('SELECT * FROM "'+table+'"'));now=Counter(tuple(r) for r in current.execute('SELECT * FROM "'+table+'"'))
            checks[table]=not (before-now) if append_only else before==now
        assert current.execute('PRAGMA integrity_check').fetchone()[0]=='ok' and not current.execute('PRAGMA foreign_key_check').fetchall()
    return checks


if __name__=='__main__':
    protected=json.loads((BASE/'baseline/protected.json').read_text())
    changed=[p for p,h in protected.items() if hashlib.sha256(Path(p).read_bytes()).hexdigest()!=h]
    portal=compare(BASE/'baseline/portal.sqlite3',ROOT/'data/education.sqlite3')
    ai=compare(BASE/'baseline/ai.sqlite3',ROOT/'data/ai-staging.sqlite3',True)
    key=(ROOT/'.secrets/ai_admin_key').read_text().strip()
    with httpx.Client(trust_env=False,headers={'Authorization':'Bearer '+key},timeout=10) as client:
        health=client.get('http://127.0.0.1:8010/health').json();runtime=client.get('http://127.0.0.1:8010/v1/runtime').json()
    assert health['build']['ai_source_sha256']==source_fingerprint() and not health['real_device_enrollment_enabled'] and not health['active_connections']
    paths=[ROOT/'.secrets/ai_admin_key',ROOT/'.secrets/ai_device_issuer_key',BASE/'qa/admin-key',BASE/'qa/ai_device_issuer_key',ROOT.parent/'Wewin Connector/Wewin_AI_Connector/.secrets/admin_sync_token']
    secrets=[p.read_bytes().strip() for p in paths if p.is_file()]
    files=[ROOT/p.decode() for p in subprocess.check_output(['git','ls-files','-z'],cwd=ROOT).split(b'\0') if p]
    files += [p for p in (ROOT/'frontend/dist').rglob('*') if p.is_file()]
    leaks=[str(p.relative_to(ROOT)) for p in files if p.is_file() and any(s and s in p.read_bytes() for s in secrets)]
    logs=list(BASE.rglob('*.log'))+list((ROOT/'logs').glob('device-*.log'))
    raw_urls=[str(p.relative_to(ROOT)) for p in logs if re.search(r'/xiaozhi/ota/bootstrap/[A-Za-z0-9_-]{40,80}',p.read_text(encoding='utf-8',errors='ignore'))]
    production_manifest=Path.home()/'.ollama/models/manifests/registry.ollama.ai/library/qwen3/4b'
    isolated_manifest=ROOT/'data/ai-eval-models/manifests/registry.ollama.ai/library/qwen3/4b'
    manifest_equal=production_manifest.read_bytes()==isolated_manifest.read_bytes()
    result={'protected_files':len(protected),'protected_changed':changed,'portal_business_tables_unchanged':portal,'baseline_ai_rows_preserved':ai,'integrity_and_foreign_keys':'PASS','new_simulator_audit_session_agent_rows_allowed':True,'production_4b_manifest_matches_readonly_eval_copy':manifest_equal,'secret_leaks':leaks,'raw_bootstrap_urls_in_logs':raw_urls,'health':health,'device_origin':runtime['device_origin'],'trusted_tls_edge':runtime['trusted_tls_edge'],'physical_changes_performed':False}
    (BASE/'protection-final.json').write_text(json.dumps(result,indent=2));print(json.dumps({'protected_unchanged':len(protected)-len(changed),'portal_preserved':all(portal.values()),'baseline_ai_preserved':all(ai.values()),'secret_leaks':len(leaks),'raw_url_log_leaks':len(raw_urls)}))
    assert not changed and all(portal.values()) and all(ai.values()) and manifest_equal and not leaks and not raw_urls
