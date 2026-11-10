"""Explicit simulator: actual local speech/LLM/Opus, never physical robot proof."""
import argparse
import asyncio
import json
import time
from pathlib import Path
from uuid import uuid4
import httpx
import numpy as np
import soundfile as sf
import websockets
from .settings import Settings,ROOT
from .audio import encode_audio,opus_library


async def simulate(agent_id,text,audio,out,automatic=False,language='en',origin='http://127.0.0.1:8010',key_file=None):
    if origin not in ('http://127.0.0.1:8010','http://127.0.0.1:8011'):raise ValueError('Simulator only accepts local staging 8010/8011')
    settings=Settings(key_file=Path(key_file)) if key_file else Settings()
    with httpx.Client(base_url=origin,timeout=15,headers={'Authorization':'Bearer '+settings.admin_key()},trust_env=False) as client:
        registration={'device_id':'sim-'+uuid4().hex,'client_id':'client-'+uuid4().hex,'agent_id':agent_id,'kind':'simulator'}
        result=client.post('/v1/devices',json=registration);result.raise_for_status()
        token=result.json()['device_token']
        snapshot=client.get('/v1/agents/'+agent_id);snapshot.raise_for_status();snapshot=snapshot.json()
    input_frames=[]
    if audio:
        from supertonic import TTS
        engine=TTS(model_dir=settings.tts_models,auto_download=False,intra_op_num_threads=2,inter_op_num_threads=1)
        wave,_=engine.synthesize(text,voice_style=engine.get_voice_style('M1'),lang=language,speed=1,verbose=False,total_steps=5)
        out.mkdir(parents=True,exist_ok=True)
        sf.write(out/'input.wav',wave.reshape(-1),engine.sample_rate)
        input_frames=encode_audio(wave.reshape(-1),engine.sample_rate,16000)
        if automatic:input_frames+=encode_audio(np.zeros(16000*2,dtype=np.float32),16000,16000)
        del engine
    started=time.monotonic();received=[];events=[];metadata=None;first_audio=None
    headers={'Authorization':'Bearer '+token,'Device-Id':registration['device_id'],'Client-Id':registration['client_id'],'Protocol-Version':'1'}
    async with websockets.connect(origin.replace('http://','ws://')+'/xiaozhi/v1/',additional_headers=headers,proxy=None,open_timeout=5,max_size=65536) as ws:
        await ws.send(json.dumps({'type':'hello','version':1,'transport':'websocket','features':{'mcp':True},'audio_params':{'format':'opus','sample_rate':16000,'channels':1,'frame_duration':60}}))
        hello=json.loads(await asyncio.wait_for(ws.recv(),10));assert hello['type']=='hello'
        if audio:
            await ws.send(json.dumps({'type':'listen','state':'start','mode':'auto' if automatic else 'manual'}))
            for frame in input_frames:
                await ws.send(frame);await asyncio.sleep(.06)
            if not automatic:await ws.send(json.dumps({'type':'listen','state':'stop'}))
        else:await ws.send(json.dumps({'type':'listen','state':'detect','text':text}))
        while True:
            item=await asyncio.wait_for(ws.recv(),120)
            if isinstance(item,bytes):
                if first_audio is None:first_audio=time.monotonic()-started
                received.append(item);continue
            item=json.loads(item);events.append(item)
            if item.get('type')=='mcp':
                rpc=item['payload'];method=rpc.get('method')
                if method=='initialize':result={'protocolVersion':'2024-11-05','capabilities':{'tools':{}},'serverInfo':{'name':'explicit-wewin-simulator','version':'1'}}
                elif method=='tools/list':result={'tools':[]}
                else:continue
                await ws.send(json.dumps({'type':'mcp','payload':{'jsonrpc':'2.0','id':rpc['id'],'result':result}}))
            if item.get('type')=='wewin_config':metadata=item
            if item.get('type')=='error':raise RuntimeError(item['message'])
            if item.get('type')=='tts' and item.get('state')=='stop':break
    assert received and metadata and metadata['revision']==snapshot['revision'] and metadata['config_hash']==snapshot['config_hash']
    decoder=opus_library().Decoder(24000,1)
    pcm=b''.join(decoder.decode(frame,1440,False) for frame in received)
    out.mkdir(parents=True,exist_ok=True);sf.write(out/'response.wav',np.frombuffer(pcm,dtype='<i2'),24000,subtype='PCM_16')
    result={'evidence':'SIMULATOR_ONLY','physical_robot_verified':False,'agent_id':agent_id,'input_mode':'real_tts_opus_asr' if audio else 'text_simulator',
            'automatic_vad':automatic,'input_frames':len(input_frames),'output_opus_frames':len(received),'first_audio_seconds':round(first_audio,2),'elapsed_seconds':round(time.monotonic()-started,2),'metadata':metadata,'events':events}
    (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('events','metadata')},ensure_ascii=False))
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--agent',required=True);parser.add_argument('--text',default='Hello Win. Please teach me the English word apple.');parser.add_argument('--audio',action='store_true');parser.add_argument('--auto',action='store_true');parser.add_argument('--lang',default='en',choices=['en','vi']);parser.add_argument('--out',default=str(ROOT/'artifacts/self-hosted/simulator'))
    parser.add_argument('--origin',default='http://127.0.0.1:8010',choices=['http://127.0.0.1:8010','http://127.0.0.1:8011']);parser.add_argument('--key-file',type=Path)
    args=parser.parse_args();asyncio.run(simulate(args.agent,args.text,args.audio,Path(args.out),args.auto,args.lang,args.origin,args.key_file))
