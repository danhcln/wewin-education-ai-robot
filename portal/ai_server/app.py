import asyncio
import hashlib
import json
import secrets
import time
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI,Depends,Header,HTTPException,Request,WebSocket
from fastapi.responses import JSONResponse
from .settings import Settings
from .store import connect,migrate,digest,audit
from .providers import Providers,ProviderError
from .models import ApplyRequest,DeviceRegistration,Confirmation
from .gateway import serve_device
from .runtime import startup_build
from .policy import effective_prompt
from . import device_management as dm
from .independence import reject_legacy


def create_app(settings=None,providers=None):
    settings=settings or Settings()
    for target in (settings.ollama,settings.public_ws,settings.device_origin):reject_legacy(target)
    providers=providers or Providers(settings)
    runtime={};agent_locks={};connections={};attempts={};build=startup_build()
    mqtt_gateway=None

    @asynccontextmanager
    async def lifespan(app):
        nonlocal mqtt_gateway
        migrate(settings)
        # Incomplete old process sessions are not current connection evidence.
        with connect(settings) as db:db.execute('UPDATE sessions SET ended_at=? WHERE ended_at IS NULL',(int(time.time()),))
        if settings.mqtt_enabled:
            from .mqtt_udp import MQTTUDP
            async def mqtt_serve(socket):
                await serve_device(socket,settings,providers,load_profile,connections,transport='udp')
            mqtt_gateway=MQTTUDP(settings,mqtt_serve,connections)
            await mqtt_gateway.start()
            app.state.mqtt_gateway=mqtt_gateway
        try:
            yield
        finally:
            if mqtt_gateway:await mqtt_gateway.stop()

    app=FastAPI(title='WeWIN AI staging',version='0.1.0',lifespan=lifespan)
    app.state.settings=settings;app.state.providers=providers;app.state.runtime=runtime

    @app.middleware('http')
    async def headers(request:Request,call_next):
        if len(request.url.query)>0:return JSONResponse({'detail':'Query credentials/parameters not accepted'},status_code=400)
        size=request.headers.get('content-length','0')
        if size.isdigit() and int(size)>65536:return JSONResponse({'detail':'Payload too large'},status_code=413)
        response=await call_next(request)
        response.headers['Cache-Control']='no-store';response.headers['X-Content-Type-Options']='nosniff'
        return response

    def admin(authorization:str=Header(default='')):
        key=settings.admin_key()
        if not key or not secrets.compare_digest(authorization,'Bearer '+key):raise HTTPException(401,'AI server management authentication required')

    def rate(action,maximum=60):
        now=time.monotonic();start,count=attempts.get(action,(now,0))
        if now-start>=60:start,count=now,0
        if count>=maximum:raise HTTPException(429,'AI staging rate limit')
        attempts[action]=(start,count+1)

    def compile_profile(row):
        profile=json.loads(row['payload'])
        prompt=effective_prompt(profile)
        return {'agent_id':row['id'],'revision':row['revision'],'config':profile,'config_hash':row['hash'],'effective_prompt':prompt,'effective_prompt_hash':digest(prompt),'loaded':True,'state':'server_applied_verified','device_verified':False,'runtime_dependencies':{'asr_model':settings.asr_model,'tts_model':settings.tts_models,'mcp_tools':['wewin_search','wewin_get_programs','wewin_test_connection'],'knowledge_binding':'wewin_public_readonly','external_agent_configuration':False}}

    async def load_profile(agent_id):
        with connect(settings) as db:row=db.execute('SELECT * FROM agents WHERE id=?',(agent_id,)).fetchone()
        if row is None:raise HTTPException(404,'AI Agent not found')
        if agent_id not in runtime or runtime[agent_id]['revision']!=row['revision']:
            await providers.load()
            runtime[agent_id]=compile_profile(row)
        return dict(runtime[agent_id])

    @app.exception_handler(ProviderError)
    async def provider_error(request,exc):
        return JSONResponse({'detail':str(exc),'state':'apply_failed'},status_code=503)

    @app.get('/health')
    async def health():
        return {'status':'ok','service':'wewin-ai-staging','build':build,'transport':'websocket-v1','mqtt_udp':bool(mqtt_gateway and mqtt_gateway.server and mqtt_gateway.server.is_serving()),'mqtt_udp_physical_enabled':False,'firmware_delivery':False,'real_device_enrollment_enabled':settings.real_devices,'active_connections':len(connections),'simulator_connections':sum(c['kind']=='simulator' for c in connections.values()),'physical_connections':sum(c['kind']=='physical' for c in connections.values()),'asr_loaded':providers.asr is not None,'tts_loaded':providers.tts is not None}

    @app.get('/v1/runtime',dependencies=[Depends(admin)])
    async def runtime_info():
        return {'build':build,'database':str(settings.db.resolve()),'key_file':str(settings.key_file.resolve()),'ollama':settings.ollama,'asr_model':settings.asr_model,'tts_models':settings.tts_models,'connector_db':str(settings.connector_db.resolve()),'public_ws':settings.public_ws,'device_origin':settings.device_origin,'trusted_tls_edge':settings.trusted_tls_edge,'device_issuer_configured':settings.device_issuer_file.is_file(),'physical_enrollment':settings.real_devices,'llm_stream':settings.llm_stream,'tokenizer_local':bool(settings.tokenizer and Path(settings.tokenizer).is_file())}

    @app.get('/v1/agents',dependencies=[Depends(admin)])
    async def agents(x_wewin_owner:str=Header(default=''),x_wewin_tenant:str=Header(default='')):
        owner,tenant=dm.scope(x_wewin_owner,x_wewin_tenant)
        with connect(settings) as db:
            rows=db.execute("SELECT a.id,json_extract(a.payload,'$.robot_name') AS name,a.revision,a.hash,a.updated_at FROM agents a LEFT JOIN agent_owners o ON o.agent_id=a.id WHERE (?='' OR o.owner_id=? AND o.tenant_id=?) ORDER BY a.id LIMIT 100",(owner,owner,tenant)).fetchall()
        return {'items':[dict(r) for r in rows]}

    @app.get('/v1/devices',dependencies=[Depends(admin)])
    async def devices():
        with connect(settings) as db:rows=db.execute('SELECT id,client_id,agent_id,kind,revoked FROM devices ORDER BY id LIMIT 100').fetchall()
        return {'items':[dict(r) for r in rows]}

    @app.post('/v1/devices/{device_id}/revoke',dependencies=[Depends(admin)])
    async def revoke(device_id:str,body:Confirmation,x_wewin_owner:str=Header(default=''),x_wewin_tenant:str=Header(default='')):
        if not body.confirmed:raise HTTPException(422,'Explicit revocation confirmation required')
        with connect(settings) as db:
            if db.execute('SELECT 1 FROM managed_devices WHERE device_id=?',(device_id,)).fetchone():dm.owned_device(db,device_id,*dm.scope(x_wewin_owner,x_wewin_tenant,True))
            changed=db.execute('UPDATE devices SET revoked=1 WHERE id=?',(device_id,)).rowcount
            if not changed:raise HTTPException(404,'Device not found')
            audit(db,'device_credential_revoked',device_id)
        active=connections.get(device_id)
        if active:await active['socket'].close(code=1008)
        return {'state':'revoked'}

    @app.get('/v1/catalog',dependencies=[Depends(admin)])
    async def catalog():
        return await providers.catalog()

    @app.get('/v1/agents/{agent_id}',dependencies=[Depends(admin)])
    async def get_agent(agent_id:str,x_wewin_owner:str=Header(default=''),x_wewin_tenant:str=Header(default='')):
        with connect(settings) as db:dm.agent_scope(db,agent_id,*dm.scope(x_wewin_owner,x_wewin_tenant))
        return await load_profile(agent_id)

    @app.put('/v1/agents/{agent_id}',dependencies=[Depends(admin)])
    async def apply(agent_id:str,body:ApplyRequest,x_wewin_owner:str=Header(default=''),x_wewin_tenant:str=Header(default='')):
        owner,tenant=dm.scope(x_wewin_owner,x_wewin_tenant)
        rate('apply',30)
        if not agent_id or len(agent_id)>120 or not all(c.isalnum() or c in '_-' for c in agent_id):raise HTTPException(422,'Invalid Agent ID')
        payload=body.config.model_dump();request_hash=digest({'agent_id':agent_id,**body.model_dump()})
        lock=agent_locks.setdefault(agent_id,asyncio.Lock())
        async with lock:
            with connect(settings) as db:
                dm.agent_scope(db,agent_id,owner,tenant,mutation=True)
                old=db.execute('SELECT * FROM operations WHERE id=?',(body.operation_id,)).fetchone()
                current=db.execute('SELECT revision FROM agents WHERE id=?',(agent_id,)).fetchone()
            if old:
                if old['agent_id']!=agent_id or old['request_hash']!=request_hash:raise HTTPException(409,'Operation ID conflict')
                result=await load_profile(agent_id)
                return {**result,'operation_revision':old['revision'],'idempotent_replay':True}
            if (current[0] if current else 0)!=body.expected_revision:raise HTTPException(409,'Agent revision conflict')
            catalog=await providers.catalog()
            if payload['ai_model'] not in {m['id'] for m in catalog['models']} or payload['voice'] not in {v['id'] for v in catalog['voices']} or payload['language'] not in {v['id'] for v in catalog['languages']}:
                raise HTTPException(422,'Model/voice absent from actual provider catalog')
            await providers.load()
            revision=body.expected_revision+1;now=int(time.time());config_hash=digest(payload)
            with connect(settings) as db:
                db.execute('BEGIN IMMEDIATE')
                current=db.execute('SELECT revision FROM agents WHERE id=?',(agent_id,)).fetchone()
                if (current[0] if current else 0)!=body.expected_revision:raise HTTPException(409,'Agent revision conflict')
                db.execute('INSERT INTO agents VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET revision=excluded.revision,payload=excluded.payload,hash=excluded.hash,updated_at=excluded.updated_at',(agent_id,revision,json.dumps(payload,ensure_ascii=False),config_hash,now))
                if owner:db.execute('INSERT OR IGNORE INTO agent_owners VALUES(?,?,?,?)',(agent_id,owner,tenant,now))
                db.execute('INSERT INTO agent_versions VALUES(?,?,?,?,?)',(agent_id,revision,json.dumps(payload,ensure_ascii=False),config_hash,now))
                db.execute('INSERT INTO operations VALUES(?,?,?,?)',(body.operation_id,agent_id,request_hash,revision))
                audit(db,'agent_runtime_applied',agent_id,revision)
                row=db.execute('SELECT * FROM agents WHERE id=?',(agent_id,)).fetchone()
            runtime[agent_id]=compile_profile(row)
            return await load_profile(agent_id)

    @app.get('/v1/agents/{agent_id}/history',dependencies=[Depends(admin)])
    async def history(agent_id:str):
        with connect(settings) as db:rows=db.execute('SELECT revision,hash,created_at FROM agent_versions WHERE agent_id=? ORDER BY revision DESC LIMIT 100',(agent_id,)).fetchall()
        return {'items':[dict(r) for r in rows]}

    @app.post('/v1/devices',dependencies=[Depends(admin)])
    async def register(body:DeviceRegistration):
        rate('register',10)
        if body.kind=='physical':raise HTTPException(403,'Physical devices require approved managed enrollment; legacy registration is simulator-only')
        token=secrets.token_urlsafe(32)
        with connect(settings) as db:
            if not db.execute('SELECT 1 FROM agents WHERE id=?',(body.agent_id,)).fetchone():raise HTTPException(422,'Unknown Agent')
            if db.execute('SELECT 1 FROM agent_owners WHERE agent_id=?',(body.agent_id,)).fetchone():raise HTTPException(403,'Owned Agents require managed provisioning with owner scope')
            if db.execute('SELECT 1 FROM devices WHERE id=?',(body.device_id,)).fetchone():raise HTTPException(409,'Device already exists; no implicit credential rotation')
            db.execute('INSERT INTO devices VALUES(?,?,?,?,?,0)',(body.device_id,body.client_id,body.agent_id,hashlib.sha256(token.encode()).hexdigest(),body.kind))
            audit(db,'device_registered',body.device_id,body.kind)
        return {'device_id':body.device_id,'kind':body.kind,'device_token':token,'display_once':True}

    @app.get('/v1/agents/{agent_id}/evidence',dependencies=[Depends(admin)])
    async def evidence(agent_id:str):
        with connect(settings) as db:
            rows=db.execute('SELECT t.revision,t.config_hash,t.input_kind,t.elapsed_ms,t.audio_frames,t.created_at,s.kind FROM turns t JOIN sessions s ON s.id=t.session_id JOIN devices d ON d.id=s.device_id WHERE d.agent_id=? ORDER BY t.created_at DESC LIMIT 20',(agent_id,)).fetchall()
        return {'turns':[dict(r) for r in rows],'device_session_verified':False,'note':'Simulator evidence never verifies a physical robot; physical acceptance is not authorized in this task.'}

    @app.post('/xiaozhi/ota/')
    async def discovery(request:Request):
        device_id=request.headers.get('device-id','');client_id=request.headers.get('client-id','')
        token=request.headers.get('authorization','').removeprefix('Bearer ')
        with connect(settings) as db:device=db.execute('SELECT * FROM devices WHERE id=? AND client_id=? AND token_hash=? AND revoked=0',(device_id,client_id,hashlib.sha256(token.encode()).hexdigest())).fetchone() if token else None
        if not device or device['kind']=='physical':raise HTTPException(403,'Use managed bootstrap for physical devices; factory activation is not supported')
        return {'server_time':{'timestamp':int(time.time()*1000),'timezone_offset':420},'websocket':{'url':settings.public_ws,'token':token,'version':1},'firmware':{'version':'0.0.0','url':''},'wewin':{'firmware_delivery':False,'kind':device['kind']}}

    @app.websocket('/xiaozhi/v1/')
    async def gateway(ws:WebSocket):
        await serve_device(ws,settings,providers,load_profile,connections)

    @app.post('/v1/device-provisions',dependencies=[Depends(admin)])
    async def provision(body:dm.DeviceProvision,x_wewin_owner:str=Header(default=''),x_wewin_tenant:str=Header(default='')):
        rate('managed_provision',10)
        return dm.provision(settings,body,x_wewin_owner,x_wewin_tenant)

    @app.get('/v1/devices/{device_id}/diagnostics',dependencies=[Depends(admin)])
    async def device_diagnostic(device_id:str,x_wewin_owner:str=Header(default=''),x_wewin_tenant:str=Header(default='')):
        return dm.diagnostic(settings,device_id,*dm.scope(x_wewin_owner,x_wewin_tenant,True),connections)

    @app.post('/v1/devices/{device_id}/binding',dependencies=[Depends(admin)])
    async def device_bind(device_id:str,body:dm.DeviceChange,x_wewin_owner:str=Header(default=''),x_wewin_tenant:str=Header(default='')):
        return await dm.change(settings,device_id,body,x_wewin_owner,x_wewin_tenant,connections)

    @app.post('/v1/devices/{device_id}/credentials/rotate',dependencies=[Depends(admin)])
    async def device_rotate(device_id:str,body:dm.DeviceChange,x_wewin_owner:str=Header(default=''),x_wewin_tenant:str=Header(default='')):
        return await dm.change(settings,device_id,body,x_wewin_owner,x_wewin_tenant,connections,rotate=True)

    @app.post(dm.PREFIX+'{bootstrap_secret}')
    @app.post(dm.PREFIX+'{bootstrap_secret}/',include_in_schema=False)
    async def managed_discovery(bootstrap_secret:str,request:Request):
        rate('managed_bootstrap',240)
        from fastapi.responses import JSONResponse
        return JSONResponse(await dm.bootstrap(request,settings,bootstrap_secret),headers={'Cache-Control':'no-store','Referrer-Policy':'no-referrer'})

    # Outermost user middleware: also redact requests rejected early by headers.
    app.add_middleware(dm.BootstrapLogRedaction)
    return app


app=create_app()
