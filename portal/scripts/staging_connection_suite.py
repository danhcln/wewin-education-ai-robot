"""Ordered live suite, simulator only; owns a NEW uniquely named Agent/device.

No updates to existing Agents, real device enrollment, Cloud or firmware. All
mutations are scoped to qa_hardening_<uuid> on loopback AI 8010/8011. Explicit
controlled rollback restores that test Agent's profile at a new revision.
"""
import argparse
import asyncio
import json
from pathlib import Path
import sys
import time
from uuid import uuid4
import httpx
import numpy as np
import soundfile as sf
import websockets

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from ai_server.models import AgentProfile
from ai_server.settings import Settings
from ai_server.providers import Providers
from ai_server.audio import encode_audio,opus_library


def hello():return {'type':'hello','version':1,'transport':'websocket','features':{'mcp':True},'audio_params':{'format':'opus','sample_rate':16000,'channels':1,'frame_duration':60}}


async def initialize(ws):
    await ws.send(json.dumps(hello()));message=json.loads(await ws.recv());assert message['type']=='hello' and message['audio_params']['sample_rate']==24000
    session=message['session_id']
    request=json.loads(await ws.recv());assert request['payload']['method']=='initialize'
    await ws.send(json.dumps({'type':'mcp','payload':{'jsonrpc':'2.0','id':request['payload']['id'],'result':{'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'explicit-simulator','version':'1'}}}}))
    assert json.loads(await ws.recv())['payload']['method']=='notifications/initialized'
    request=json.loads(await ws.recv());assert request['payload']['method']=='tools/list'
    await ws.send(json.dumps({'type':'mcp','payload':{'jsonrpc':'2.0','id':request['payload']['id'],'result':{'tools':[]}}}))
    await asyncio.wait_for(await ws.ping(),5)
    return session


async def receive_turn(ws,out,snapshot):
    events=[];frames=[];started=time.monotonic();first=None
    while True:
        item=await asyncio.wait_for(ws.recv(),230)
        if isinstance(item,bytes):
            if first is None:first=time.monotonic()-started
            frames.append(item);continue
        event=json.loads(item);events.append(event)
        if event.get('type')=='error':raise RuntimeError(event['code'])
        if event.get('type')=='tts' and event.get('state')=='stop':break
    metadata=next(e for e in events if e['type']=='wewin_config')
    assert metadata['revision']==snapshot['revision'] and metadata['config_hash']==snapshot['config_hash'] and frames
    decoder=opus_library().Decoder(24000,1);pcm=np.frombuffer(b''.join(decoder.decode(frame,1440,False) for frame in frames),dtype='<i2')
    out.mkdir(parents=True,exist_ok=True);sf.write(out/'response.wav',pcm,24000,subtype='PCM_16')
    result={'evidence':'SIMULATOR_ONLY_REAL_ENGINES','robot_verified':False,'metadata':metadata,'events':events,'frames':len(frames),'first_audio_after_submit_s':first,'elapsed_s':time.monotonic()-started}
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    return result


async def main(args):
    if args.origin not in ('http://127.0.0.1:8010','http://127.0.0.1:8011'):raise ValueError('Only owned loopback staging')
    args.out.mkdir(parents=True,exist_ok=True);settings=Settings();key=args.key_file.read_text().strip();engines=Providers(settings)
    agent='qa_hardening_'+uuid4().hex;device='sim-'+uuid4().hex;client_id='client-'+uuid4().hex;checks=[];registered=False
    url=args.origin.replace('http://','ws://')+'/xiaozhi/v1/'
    async with httpx.AsyncClient(base_url=args.origin,headers={'Authorization':'Bearer '+key},trust_env=False,timeout=150) as admin:
        health=(await admin.get('/health')).json();assert not health['real_device_enrollment_enabled'] and health['active_connections']==0
        before=(await admin.get('/v1/agents')).json()['items']
        baseline={row['id']:row for row in before}
        profile=AgentProfile(ai_model='qwen3:4b',language='en-US',ai_role='builtin-english-teacher',role_version=1,system_prompt='You are Win, a kind English teacher. Correct mistakes briefly and accurately.').model_dump()
        async def apply(expected,body):
            response=await admin.put('/v1/agents/'+agent,json={'expected_revision':expected,'operation_id':'qa_'+uuid4().hex,'config':body});response.raise_for_status()
            actual=(await admin.get('/v1/agents/'+agent)).json();assert actual['loaded'] and actual['config']==body
            return actual
        snapshot=await apply(0,profile)
        registration=await admin.post('/v1/devices',json={'device_id':device,'client_id':client_id,'agent_id':agent});registration.raise_for_status();registered=True
        headers={'Authorization':'Bearer '+registration.json()['device_token'],'Device-Id':device,'Client-Id':client_id,'Protocol-Version':'1'}
        try:
            assert (await admin.post('/xiaozhi/ota/',headers={**headers,'Authorization':'Bearer invalid'})).status_code==403
            ota=await admin.post('/xiaozhi/ota/',headers=headers);ota.raise_for_status();assert ota.json()['firmware']['url']=='' and ota.json()['websocket']['version']==1
            checks.append('authentication_and_enrolled_ota_discovery')
            try:
                async with websockets.connect(url,additional_headers={**headers,'Client-Id':'wrong-client'},proxy=None):raise AssertionError('Wrong client admitted')
            except websockets.exceptions.InvalidStatus:pass
            async with websockets.connect(url,additional_headers=headers,proxy=None) as ws:
                session=await initialize(ws);checks.append('wsv1_hello_session_and_ping')
                await engines.load();wave,rate=await engines.synthesize('Please correct this sentence: she go to school.',{'voice':'M1','language':'en-US','speech_rate':1})
                sf.write(args.out/'input.wav',wave,rate)
                await ws.send(json.dumps({'type':'listen','state':'start','mode':'manual','session_id':session}))
                for frame in encode_audio(wave,rate,16000):await ws.send(frame);await asyncio.sleep(.06)
                await ws.send(json.dumps({'type':'listen','state':'stop','session_id':session}))
                first=await receive_turn(ws,args.out/'teacher',snapshot);checks+=['opus_uplink_asr','validated_llm_tts_opus_downlink']
                await ws.send(json.dumps({'type':'listen','state':'detect','text':'WeWIN test connection'}))
                tool=await receive_turn(ws,args.out/'mcp',snapshot);assert 'wewin_test_connection' in tool['metadata']['tools'];checks.append('public_readonly_mcp')
                changed={**profile,'ai_role':'builtin-consultant','language':'vi-VN','system_prompt':'Bạn là Win, tư vấn viên WeWIN. Chỉ dùng thông tin public tool, không bịa học phí.'}
                snapshot=await apply(1,changed);checks.append('configuration_apply_readback')
                await ws.send(json.dumps({'type':'listen','state':'detect','text':'WeWIN có những khóa học nào?'}))
                switched=await receive_turn(ws,args.out/'consultant',snapshot);assert 'wewin_get_programs' in switched['metadata']['tools'];checks.append('role_switch_next_turn')
                restored=await apply(2,profile);assert restored['revision']==3;checks.append('controlled_test_agent_rollback_readback')
                await ws.send(json.dumps({'type':'listen','state':'start','mode':'manual'}));await ws.send(b'\xff'*4096)
                try:await ws.recv();raise AssertionError('Corrupt Opus admitted')
                except websockets.exceptions.ConnectionClosed:pass
            async with websockets.connect(url,additional_headers=headers,proxy=None) as ws:
                next_session=await initialize(ws);assert next_session!=session
                await ws.send(json.dumps({'type':'abort'}));assert json.loads(await ws.recv())['state']=='stop'
                checks+=['reconnect_new_session','malformed_audio_error_recovery']
            after={r['id']:r for r in (await admin.get('/v1/agents')).json()['items']}
            assert all(after.get(i)==row for i,row in baseline.items());checks.append('existing_agents_unchanged')
            result={'origin':args.origin,'agent':agent,'simulator_only':True,'physical_verified':False,'checks_passed':checks,'build':health.get('build'),'existing_agent_count':len(baseline),'rollback_revision':3}
            (args.out/'results.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)
        finally:
            if registered:await admin.post('/v1/devices/'+device+'/revoke',json={'confirmed':True})
            engines.cpu.shutdown(wait=True,cancel_futures=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--origin',default='http://127.0.0.1:8010');parser.add_argument('--key-file',type=Path,default=ROOT/'.secrets/ai_admin_key');parser.add_argument('--out',type=Path,default=ROOT/'artifacts/staging-hardening/post-restart');asyncio.run(main(parser.parse_args()))
