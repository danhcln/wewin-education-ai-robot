"""Private security-compatible snapshot. No overwrite, reset, upload or restart."""
import json
from pathlib import Path
import sqlite3
import sys
from uuid import uuid4
import httpx

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ai_server.settings import Settings


if __name__=='__main__':
    settings=Settings();out=ROOT/'artifacts/independent-migration'/('enrolled-backup-'+uuid4().hex[:8])
    with httpx.Client(base_url='http://127.0.0.1:8010',headers={'Authorization':'Bearer '+settings.admin_key()},trust_env=False,timeout=10) as client:
        response=client.get('/health');response.raise_for_status();health=response.json()
        assert health['service']=='wewin-ai-staging' and not health['active_connections'] and not health['real_device_enrollment_enabled']
        runtime=client.get('/v1/runtime');runtime.raise_for_status();runtime=runtime.json()
        assert Path(runtime['database']).resolve()==settings.db.resolve()
    if not settings.device_issuer_file.is_file():raise RuntimeError('Provisioned issuer backup required; never silently replace it')
    out.mkdir(exist_ok=False)
    for source,target in ((settings.db,'ai.sqlite3'),(ROOT/'data/education.sqlite3','portal.sqlite3')):
        with sqlite3.connect(source.resolve().as_uri()+'?mode=ro',uri=True) as current,sqlite3.connect(out/target) as backup:current.backup(backup)
    (out/'ai-admin-key').write_bytes(settings.key_file.read_bytes())
    (out/'ai-device-issuer-key').write_bytes(settings.device_issuer_file.read_bytes())
    # Keep manifest private alongside its DB; it contains no raw key or bootstrap.
    (out/'manifest.json').write_text(json.dumps({'health':health,'runtime':runtime,'scope':'security-compatible source+DB+issuer recovery only; reconcile latest revocations before serving ingress','legacy_source_downgrade_allowed':False},indent=2))
    print(json.dumps({'private_backup':str(out),'issuer_backed_up':True,'uploaded':False,'reset_or_downgrade':False}))
