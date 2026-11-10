import asyncio
import hashlib
import json
import time
import unicodedata
import re
from uuid import uuid4
from fastapi import WebSocket,WebSocketDisconnect
from .audio import OpusInput,SpeechBoundary,encode_audio
from .store import connect,audit
from .mcp_client import MCPClient
from .device_management import binding_valid,tls_required


async def serve_device(ws:WebSocket,settings,providers,load_profile,connections,transport='websocket'):
    token=ws.headers.get('authorization','').removeprefix('Bearer ')
    device_id=ws.headers.get('device-id','');client_id=ws.headers.get('client-id','')
    with connect(settings) as db:
        row=db.execute('SELECT * FROM devices WHERE (id=? OR id=?) AND client_id=? AND token_hash=? AND revoked=0',(device_id,device_id.lower(),client_id,hashlib.sha256(token.encode()).hexdigest())).fetchone() if token else None
    if row is None or ws.headers.get('origin') or ws.url.query or ws.headers.get('protocol-version','1')!='1':
        await ws.close(code=1008);return
    device=dict(row)
    device_id=device['id']
    with connect(settings) as db:
        if not binding_valid(db,device):await ws.close(code=1008);return
        managed=db.execute('SELECT 1 FROM managed_devices WHERE device_id=?',(device_id,)).fetchone()
        require_tls=bool(managed and tls_required(db,settings,device_id))
    # Once WeWIN issues HTTPS bootstrap, its managed bearer must not downgrade
    # to a plaintext WS listener (legacy loopback simulators remain separate).
    if require_tls and not (transport=='udp' and ws.secure) and (not settings.trusted_tls_edge or ws.client.host!='127.0.0.1' or ws.headers.get('x-wewin-edge-tls')!='1'):
        await ws.close(code=1008);return
    if device['kind']=='physical' and (not settings.real_devices or transport!='websocket'):
        await ws.close(code=1008);return
    if device['kind']=='physical' and (not settings.trusted_tls_edge or ws.client.host!='127.0.0.1' or ws.headers.get('x-wewin-edge-tls')!='1'):
        await ws.close(code=1008);return
    if device_id in connections or len(connections)>=8:
        await ws.close(code=1013);return
    connections[device_id]={'socket':ws,'kind':device['kind'],'transport':transport,'hello_verified':False,'last_message_at':int(time.time())}
    session_id=uuid4().hex;task=None;audio=bytearray();listening=False;decoder=None;history=[];history_revision=None;automatic=False;boundary=None
    await ws.accept()
    with connect(settings) as db:
        db.execute('INSERT INTO sessions VALUES(?,?,?,?,NULL)',(session_id,device_id,device['kind'],int(time.time())))
        audit(db,'device_connected',device_id,device['kind'])

    async def send(data):
        await ws.send_json({'session_id':session_id,**data})

    async def cancel_turn():
        nonlocal task
        if task:
            task.cancel()
            try:await task
            except (asyncio.CancelledError,Exception):pass
            task=None

    async def turn(pcm=None,text=None,greeting=False):
        nonlocal history,history_revision
        started=time.monotonic()
        try:
            async with providers.turn_slots:
                snapshot=await load_profile(device['agent_id'])
                profile=snapshot['config'];revision=snapshot['revision']
                with connect(settings) as db:audit(db,'turn_started',session_id,'greeting' if greeting else 'text' if text is not None else 'opus_audio')
                with connect(settings) as db:audit(db,'turn_profile',session_id,json.dumps({'revision':revision,'config_hash':snapshot['config_hash'],'effective_prompt_hash':snapshot.get('effective_prompt_hash')}))
                if revision!=history_revision:history=[];history_revision=revision
                if greeting:utterance='';answer=profile['greeting'];tools_used=[]
                else:
                    utterance=text if text is not None else await providers.transcribe(bytes(pcm),language=profile['language'].split('-')[0])
                    with connect(settings) as db:audit(db,'asr_or_text_ready',session_id,int((time.monotonic()-started)*1000))
                    if not utterance:raise ValueError('Không nhận diện được lời nói')
                    await send({'type':'stt','text':utterance})
                    messages=[{'role':'system','content':snapshot['effective_prompt']},*history,{'role':'user','content':utterance}]
                    tools_used=[]
                    async with MCPClient(settings) as mcp:
                        # Explicit server policy for institution facts, not a fabricated model tool call.
                        folded=re.sub('[^a-z0-9]','',unicodedata.normalize('NFD',utterance.lower()).encode('ascii','ignore').decode())
                        institution_query='wewin' in folded or profile['ai_role']=='builtin-consultant'
                        if institution_query:
                            name='wewin_get_programs' if any(w in folded for w in ('khoahoc','course')) else 'wewin_test_connection' if 'test' in folded else 'wewin_search'
                            result=await mcp.request('tools/call',{'name':name,'arguments':{'query':utterance} if name=='wewin_search' else {}})
                            tools_used.append(name)
                            messages.append({'role':'tool','tool_name':name,'content':json.dumps(result,ensure_ascii=False)})
                        with connect(settings) as db:audit(db,'llm_started',session_id,len(tools_used))
                        message=await providers.llm(messages,profile['ai_model'])
                        with connect(settings) as db:audit(db,'llm_metrics',session_id,json.dumps(message.get('metrics',{})))
                        with connect(settings) as db:audit(db,'llm_response_ready',session_id,int((time.monotonic()-started)*1000))
                        answer=str(message.get('content','')).strip()
                    if not answer:raise ValueError('LLM trả về nội dung trống')
                    history=(history+[{'role':'user','content':utterance},{'role':'assistant','content':answer}])[-8:]
                wave,rate=await providers.synthesize(answer[:1200],profile)
                with connect(settings) as db:audit(db,'tts_audio_ready',session_id,int((time.monotonic()-started)*1000))
                frames=await asyncio.to_thread(encode_audio,wave,rate)
                if not frames or len(frames)>2000:raise ValueError('TTS output vượt giới hạn')
                await send({'type':'tts','state':'start'})
                await send({'type':'tts','state':'sentence_start','text':answer})
                if device['kind']=='simulator':
                    await send({'type':'wewin_config','revision':revision,'config_hash':snapshot['config_hash'],'evidence':'simulator_only','tools':tools_used})
                deadline=time.monotonic()
                for index,frame in enumerate(frames):
                    await asyncio.sleep(max(0,deadline-time.monotonic()))
                    await ws.send_bytes(frame)
                    if index==0:
                        with connect(settings) as db:audit(db,'first_audio_sent',session_id,int((time.monotonic()-started)*1000))
                    # Do not accumulate send-time drift or burst to catch up
                    # after a stalled socket/event loop.
                    now=time.monotonic()
                    deadline=now+.06 if now-deadline>.12 else deadline+.06
                await asyncio.sleep(max(0,deadline-time.monotonic()))
                await send({'type':'tts','state':'stop'})
                with connect(settings) as db:
                    db.execute('INSERT INTO turns VALUES(?,?,?,?,?,?,?,?,?,?,?)',(uuid4().hex,session_id,revision,snapshot['config_hash'],'greeting' if greeting else 'text' if text is not None else 'opus_audio',None,'sha256:'+hashlib.sha256(answer.encode()).hexdigest(),json.dumps(tools_used),int((time.monotonic()-started)*1000),len(frames),int(time.time())))
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            from .providers import ProviderError
            detail=type(exc).__name__+(': '+str(exc)[:160] if isinstance(exc,ProviderError) else '')
            with connect(settings) as db:audit(db,'turn_failed',session_id,detail)
            try:
                await send({'type':'error','code':'pipeline_failed','message':'ASR/LLM/TTS/MCP lỗi hoặc quá thời gian; không có audio thay thế.'})
                await send({'type':'tts','state':'stop'})
            except (RuntimeError,WebSocketDisconnect):pass

    async def bounded_turn(**kwargs):
        try:await asyncio.wait_for(turn(**kwargs),settings.provider_timeout+140)
        except asyncio.TimeoutError:
            with connect(settings) as db:audit(db,'turn_timed_out',session_id)
            try:
                await send({'type':'error','code':'turn_timeout','message':'Lượt thoại quá thời gian; hãy thử lại.'})
                await send({'type':'tts','state':'stop'})
            except (RuntimeError,WebSocketDisconnect):pass

    try:
        hello=await asyncio.wait_for(ws.receive_json(),10)
        if not isinstance(hello,dict):raise ValueError('HELLO must be an object')
        params=hello.get('audio_params') or {}
        version=3 if transport=='udp' else 1
        if not isinstance(params,dict) or not isinstance(hello.get('features',{}),dict) or hello.get('type')!='hello' or hello.get('transport')!=transport or hello.get('version')!=version or any(params.get(k)!=v for k,v in {'format':'opus','sample_rate':16000,'channels':1,'frame_duration':60}.items()):
            await ws.close(code=1008);return
        decoder=OpusInput()
        connections[device_id]['hello_verified']=True
        await send({'type':'hello','version':version,'transport':transport,'audio_params':{'format':'opus','sample_rate':24000,'channels':1,'frame_duration':60}})
        # Discovery only: no device tool call and no Bluetooth mutation.
        if (hello.get('features') or {}).get('mcp'):
            await send({'type':'mcp','payload':{'jsonrpc':'2.0','id':1,'method':'initialize','params':{'protocolVersion':'2024-11-05','capabilities':{},'clientInfo':{'name':'wewin-ai','version':'1'}}}})
        count=0;window=time.monotonic()
        while True:
            try:message=await asyncio.wait_for(ws.receive(),120)
            except asyncio.TimeoutError:
                if task and not task.done():continue
                raise
            if message['type']=='websocket.disconnect':break
            connections[device_id]['last_message_at']=int(time.time())
            with connect(settings) as db:still_authorized=binding_valid(db,device)
            if not still_authorized:await ws.close(code=1008);break
            if time.monotonic()-window>60:count=0;window=time.monotonic()
            count+=1
            if count>1600:await ws.close(code=1008);break
            if message.get('bytes') is not None:
                if not listening:continue
                if len(audio)>=16000*2*45:raise ValueError('Audio state/limit')
                pcm=decoder.decode(message['bytes']);audio.extend(pcm)
                if automatic and boundary.finished(pcm):
                    listening=False;await cancel_turn()
                    task=asyncio.create_task(bounded_turn(pcm=bytes(audio)))
                    audio.clear()
                continue
            raw=message.get('text','')
            if len(raw)>16384:raise ValueError('JSON limit')
            data=json.loads(raw)
            if not isinstance(data,dict):raise ValueError('Message must be an object')
            if data.get('session_id',session_id)!=session_id:raise ValueError('Session mismatch')
            if data.get('type')=='abort':
                await cancel_turn();audio.clear();listening=False
                await send({'type':'tts','state':'stop'})
            elif data.get('type')=='listen':
                state=data.get('state')
                if state=='start':
                    await cancel_turn();audio.clear();listening=True;decoder=OpusInput()
                    automatic=data.get('mode') in ('auto','realtime');boundary=SpeechBoundary() if automatic else None
                elif state=='stop' and listening:
                    listening=False;await cancel_turn()
                    task=asyncio.create_task(bounded_turn(pcm=bytes(audio)))
                    audio.clear()
                elif state=='detect':
                    await cancel_turn()
                    text=data.get('text','')
                    if not isinstance(text,str):raise ValueError('Text must be a string')
                    text=text[:1500]
                    task=asyncio.create_task(bounded_turn(text=text,greeting=not text or text.lower() in ('hi lily','hi, lily','你好小智')))
            elif data.get('type')=='mcp':
                payload=data.get('payload',{})
                if not isinstance(payload,dict):raise ValueError('MCP payload must be an object')
                if payload.get('id')==1 and 'result' in payload:
                    await send({'type':'mcp','payload':{'jsonrpc':'2.0','method':'notifications/initialized'}})
                    await send({'type':'mcp','payload':{'jsonrpc':'2.0','id':2,'method':'tools/list','params':{}}})
                elif payload.get('id')==2:
                    with connect(settings) as db:audit(db,'device_mcp_catalog_received',session_id,'discovery_only')
    except (WebSocketDisconnect,asyncio.TimeoutError,ValueError,KeyError,TypeError):
        try:await ws.close(code=1008)
        except RuntimeError:pass
    finally:
        await cancel_turn()
        connections.pop(device_id,None)
        with connect(settings) as db:
            db.execute('UPDATE sessions SET ended_at=? WHERE id=?',(int(time.time()),session_id))
            audit(db,'device_disconnected',device_id,device['kind'])
