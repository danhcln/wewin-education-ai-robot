"""QA Portal -> actual independent AI server. Never writes the main Portal DB."""
import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlsplit
import httpx

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.integrations import settings


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--role',default='builtin-english-teacher');parser.add_argument('--origin',default='http://127.0.0.1:8002');parser.add_argument('--out',default='artifacts/self-hosted/portal-server-apply.json');parser.add_argument('--language',choices=['vi-VN','en-US','en'])
    args=parser.parse_args();parsed=urlsplit(args.origin)
    if parsed.hostname!='127.0.0.1' or parsed.port!=8002:raise ValueError('This test helper accepts only the disposable QA Portal at port 8002')
    with httpx.Client(base_url=args.origin,timeout=150,trust_env=False) as client:
        response=client.post('/api/portal/login',headers={'Origin':args.origin,'Authorization':'Bearer '+settings.ADMIN_SYNC_TOKEN});response.raise_for_status()
        headers={'Origin':args.origin,'X-WeWIN-CSRF':response.json()['csrf']}
        try:
            robots=client.get('/api/portal/robots').json()['items'];rid=robots[0]['id']
            link=client.get(f'/api/portal/robots/{rid}/self-hosted').json()['link']
            if not link or not link['enabled']:
                result=client.post(f'/api/portal/robots/{rid}/self-hosted',headers=headers,json={'confirmed':True});result.raise_for_status()
            current=client.get(f'/api/portal/robots/{rid}/config').json()
            role=client.get('/api/portal/roles/'+args.role).json()
            if args.language and args.language!=role['language']:
                from backend.roles import Role
                fields={k:role[k] for k in Role.model_fields if k in role};fields['language']=args.language
                update=client.put('/api/portal/roles/'+args.role,headers=headers,json=fields);update.raise_for_status()
                role=client.get('/api/portal/roles/'+args.role).json()
            candidate=client.post(f'/api/portal/robots/{rid}/roles/{args.role}/candidate',headers=headers,json={'version':current['version'],'role_version':role['version']});candidate.raise_for_status();candidate=candidate.json()
            assert candidate['capabilities']['apply_supported']
            # Only staging server writes are authorized by this test, never a physical robot.
            response=client.post(f'/api/portal/robots/{rid}/config/apply',headers=headers,json={'candidate_id':candidate['id'],'confirmed':True});response.raise_for_status();applied=response.json()
            assert applied['sync_state']=='server_applied_verified' and not applied['robot_applied']
            sync=client.get(f'/api/portal/robots/{rid}/config/sync-status');sync.raise_for_status();sync=sync.json()
            assert sync['server_applied'] and sync['observed']['system_prompt']==role['system_prompt'] and sync['observed']['greeting']==role['greeting']
            result={'evidence':'QA_PORTAL_TO_REAL_LOCAL_AI_SERVER','physical_robot_verified':False,'registry_record_not_physical_mapping':rid,'role_id':args.role,'role_version':role['version'],'result':applied,'sync':sync,'agent_id':candidate['capabilities']['agent_reference']}
            out=ROOT/args.out;out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
            print(json.dumps({'agent_id':result['agent_id'],'role':args.role,'server_revision':applied['server_revision'],'state':applied['sync_state'],'robot_applied':False}))
        finally:client.post('/api/portal/logout',headers=headers)


if __name__=='__main__':main()
