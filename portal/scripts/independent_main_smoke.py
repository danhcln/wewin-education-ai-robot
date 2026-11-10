"""Main8010 owned bootstrap smoke; new QA Agent/device only, always revoked.
No main Portal inventory writes, physical enrollment, models or hardware changes.
"""
import asyncio
import json
from pathlib import Path
import sys
from uuid import uuid4
import httpx
import websockets

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ai_server.models import AgentProfile
from scripts.staging_connection_suite import initialize


async def main():
    out=ROOT/'artifacts/independent-migration/main-owned-smoke';out.mkdir(exist_ok=True)
    key=(ROOT/'.secrets/ai_admin_key').read_text().strip();suffix=uuid4().hex
    agent='qa_independent_'+suffix;device='sim-owned-'+suffix;client_id='qa-client-'+suffix
    headers={'Authorization':'Bearer '+key,'X-WeWIN-Owner':'qa-staging','X-WeWIN-Tenant':'wewin-staging'}
    async with httpx.AsyncClient(base_url='http://127.0.0.1:8010',headers=headers,timeout=150,trust_env=False) as control,httpx.AsyncClient(timeout=15,trust_env=False) as network:
        health=(await control.get('/health')).json();assert not health['real_device_enrollment_enabled'] and not health['active_connections']
        result=await control.put('/v1/agents/'+agent,json={'expected_revision':0,'operation_id':'qa-'+suffix,'config':AgentProfile(ai_model='qwen3:4b',voice='F1').model_dump()});result.raise_for_status()
        readback=(await control.get('/v1/agents/'+agent)).json();assert readback['loaded'] and not readback['device_verified']
        provision=await control.post('/v1/device-provisions',json={'device_id':device,'client_id':client_id,'agent_id':agent,'kind':'simulator','ownership_attested':True,'ownership_evidence':'Owned main-staging QA simulator only','confirmed':True,'ttl_seconds':3600});provision.raise_for_status();receipt=provision.json()
        try:
            assert receipt['bootstrap_url'].startswith('http://192.168.2.10:8013/')
            native={'Device-Id':device,'Client-Id':client_id,'Activation-Version':'2'}
            boot=await network.post(receipt['bootstrap_url'],headers=native,json={'application':{'version':'main-staging-explicit-simulator'}})
            assert boot.status_code==200,'Bootstrap rejected; credential URL suppressed'
            value=boot.json();assert 'firmware' not in value and value['websocket']['url']=='ws://192.168.2.10:8013/xiaozhi/v1/'
            async with websockets.connect(value['websocket']['url'],additional_headers={**native,'Protocol-Version':'1','Authorization':'Bearer '+value['websocket']['token']},proxy=None) as ws:
                await initialize(ws)
                live=await control.get('/v1/devices/'+device+'/diagnostics');live.raise_for_status();assert live.json()['online']
                revoke=await control.post('/v1/devices/'+device+'/revoke',json={'confirmed':True});revoke.raise_for_status()
                try:await ws.recv();raise AssertionError('Revoke failed to close socket')
                except websockets.exceptions.ConnectionClosed:pass
            denied=await network.post(receipt['bootstrap_url'],headers=native,json={});assert denied.status_code==403
            result={'evidence':'MAIN_8010_LAN_SIMULATOR_ONLY','build':health['build'],'agent':agent,'device':device,'checks':['owned_agent_readback','lan_bootstrap_no_firmware_no_loopback','authenticated_wsv1_hello_mcp_ping','live_diagnostics','revoke_closes_session_and_denies_bootstrap'],'physical_verified':False,'credentials_logged':False}
            (out/'results.json').write_text(json.dumps(result,indent=2));print(json.dumps({'checks_passed':len(result['checks']),'physical_verified':False,'build':health['build']}))
        finally:await control.post('/v1/devices/'+device+'/revoke',json={'confirmed':True})


if __name__=='__main__':asyncio.run(main())
