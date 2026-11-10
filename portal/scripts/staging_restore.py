"""Real QA restore -> new candidate -> confirmed AI apply. No main Portal writes."""
import json
import sys
from pathlib import Path
import httpx
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.integrations import settings


if __name__=='__main__':
    origin='http://127.0.0.1:8002';events=[]
    with httpx.Client(base_url=origin,timeout=150,trust_env=False) as client:
        response=client.post('/api/portal/login',headers={'Origin':origin,'Authorization':'Bearer '+settings.ADMIN_SYNC_TOKEN});response.raise_for_status()
        headers={'Origin':origin,'X-WeWIN-CSRF':response.json()['csrf']}
        try:
            rid=client.get('/api/portal/robots').json()['items'][0]['id']
            for target_version in (2,3):
                base='/api/portal/robots/'+rid
                current=client.get(base+'/config').json();before=client.get(base+'/config/sync-status').json()['server_revision']
                result=client.post(base+'/config/restore',headers=headers,json={'version':current['version'],'target_version':target_version,'confirmed':True});result.raise_for_status()
                assert client.get(base+'/config/sync-status').json()['server_revision']==before
                restored=client.get(base+'/config').json()
                candidate=client.post(base+'/config/candidates',headers=headers,json={**restored['config'],'version':restored['version']});candidate.raise_for_status();candidate=candidate.json()
                applied=client.post(base+'/config/apply',headers=headers,json={'candidate_id':candidate['id'],'confirmed':True});applied.raise_for_status();applied=applied.json()
                assert applied['server_revision']==before+1 and not applied['robot_applied']
                events.append({'target_local_version':target_version,'restored_local_version':restored['version'],'applied':applied})
            (ROOT/'artifacts/self-hosted/controlled-restore.json').write_text(json.dumps(events,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps(events))
        finally:client.post('/api/portal/logout',headers=headers)
