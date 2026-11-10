from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from src.api.browser_sessions import get_store
from .service import get_service, StreamError
from fastapi import HTTPException
import logging

direct_log = logging.getLogger('WEWIN_DIRECT_TEST')

def direct_auth(request, mutating=False):
    if request.client is None or request.client.host not in ('127.0.0.1', '::1') or request.url.hostname not in ('127.0.0.1','localhost','::1'):
        raise HTTPException(403, 'Localhost lab only')
    get_store().authorize(request, mutating)

router=APIRouter(prefix='/api/stream')


class Start(BaseModel):
    model_config=ConfigDict(extra='forbid')
    endpoint:int=Field(default=-1, ge=-1, le=10000)
    peer_ipv4:str=Field(default='', max_length=15)
    port:int=Field(default=8766,ge=1024,le=65535)
    allow_system_mix:bool=False
    local_output_routed_away:bool=False


class Volume(BaseModel):
    model_config=ConfigDict(extra='forbid')
    volume:int=Field(default=70,ge=0,le=100)
    action:str=Field(default='set',max_length=16)


@router.get('/devices')
def devices(request:Request):
    get_store().authorize(request)
    return get_service().devices()


@router.get('/status')
def status(request:Request):
    get_store().authorize(request)
    return get_service().status()


@router.post('/start')
def start(body:Start,request:Request):
    get_store().authorize(request,True)
    try:return get_service().start(**body.model_dump())
    except StreamError as error:return {'status':error.code,'started':False}


@router.post('/stop')
def stop(request:Request):
    get_store().authorize(request,True)
    return get_service().stop()


@router.post('/heartbeat')
def heartbeat(request:Request):
    get_store().authorize(request,True)
    return get_service().heartbeat()


@router.post('/end')
def end(request:Request):
    get_store().authorize(request,True)
    return get_service().stop(graceful=True)

@router.post('/direct/start')
def direct_start(body: Start, request: Request):
    direct_auth(request, True)
    from src.media.device_control import get_control
    from src.media.orchestration import get_session
    control, media = get_control(), get_session()
    with media.lock:
        media_status = media.status()
        if media_status['state'] not in ('IDLE','ENDED','ERROR') or media.jobs:
            raise HTTPException(409, 'MediaSession busy')
        try:
            device = control.device()
            if device.get('file_active'):
                raise HTTPException(409, 'File audio active')
            endpoint = body.endpoint
            if endpoint < 0:
                from src.streaming.capture import loopback_devices
                devs = loopback_devices()
                def_d = next((d for d in devs if d.get('is_default')), devs[0] if devs else None)
                if not def_d:
                    raise HTTPException(400, 'Không tìm thấy thiết bị âm thanh Windows loopback')
                endpoint = def_d['index']
            direct_log.info('WEWIN_DIRECT_TEST start_requested')
            direct_log.info('WEWIN_DIRECT_TEST device_selected')
            prepared = get_service().start(endpoint=endpoint, peer_ipv4=device['ip'],
                allow_system_mix=body.allow_system_mix, local_output_routed_away=body.local_output_routed_away)
            direct_log.info('WEWIN_STREAM descriptor_ready')
            with media.lock:
                media.generation += 1
                gen = media.generation
            try:
                control.send('start', gen, prepared['descriptor'])
            except Exception:
                get_service().stop()
                raise
            media.current.update(state='DIRECT_ACTIVE',source_kind='direct_lab',generation=gen)
            direct_log.info('WEWIN_STREAM device_start_sent')
            return get_service().status()
        except (ValueError, StreamError) as error:
            raise HTTPException(409, error.code if isinstance(error, StreamError) else 'authorized_device_unavailable') from None


@router.get('/direct/status')
def direct_status(request: Request):
    direct_auth(request)
    from src.media.device_control import get_control
    s = get_service().status()
    report = s.get('device_report') or {}
    hello = bool(s.get('capture_frames') or report)
    state = s.get('state','IDLE')
    if state == 'BUFFERING': state = 'CAPTURING'
    if state == 'PLAYING' and not (hello and s.get('packets_sent',0)>0 and report.get('output_frames',0)>0): state = 'CAPTURING'
    try: device = get_control().device()
    except ValueError: device = None
    loopback = None
    try:
        from src.streaming.capture import loopback_devices
        devs = loopback_devices()
        def_d = next((d for d in devs if d.get('is_default')), devs[0] if devs else None)
        if def_d:
            loopback = {'index': def_d['index'], 'name': def_d['name'], 'clean_name': def_d.get('clean_name', def_d['name'])}
    except Exception:
        pass
    if not s.get('transport_active') and state in ('IDLE','ERROR') and device:
        native=device.get('stream',{})
        released=native.get('state')=='IDLE' or (native.get('state')=='ERROR' and native.get('owner_released') is True)
        if released and not native.get('worker_running'):
            from src.media.orchestration import get_session
            media=get_session()
            with media.lock:
                if media.current.get('source_kind')=='direct_lab' and media.current.get('state') in ('DIRECT_ACTIVE','STOPPING'):
                    media.current.update(state='IDLE')
    robot_vol = device.get('volume', 70) if device else 70
    robot_muted = device.get('muted', False) if device else False
    return {**s, 'state':state, 'hello':hello, 'device':device, 'loopback':loopback,
            'robot_volume': robot_vol, 'robot_muted': robot_muted}

@router.post('/direct/volume')
def direct_volume(body: Volume, request: Request):
    direct_auth(request, True)
    from src.media.device_control import get_control
    from src.media.orchestration import get_session
    control, media = get_control(), get_session()
    with media.lock:
        gen = media.generation
    try:
        if body.action == 'mute':
            job_id = control.mute(gen)
            return {'status': 'ok', 'action': 'mute', 'volume': 0, 'job_id': job_id}
        elif body.action == 'unmute':
            job_id = control.unmute(body.volume, gen)
            return {'status': 'ok', 'action': 'unmute', 'volume': body.volume, 'job_id': job_id}
        else:
            job_id = control.set_volume(body.volume, gen)
            return {'status': 'ok', 'action': 'set_volume', 'volume': body.volume, 'job_id': job_id}
    except ValueError as error:
        raise HTTPException(409, str(error)) from None

@router.post('/direct/stop')
def direct_stop(request: Request):
    direct_auth(request, True)
    from src.media.device_control import get_control
    from src.media.orchestration import get_session
    direct_log.info('WEWIN_DIRECT_TEST stop_requested')
    result = get_service().stop()
    media = get_session()
    with media.lock:
        media.generation += 1
        try: get_control().send('stop', media.generation)
        except ValueError: pass
    return result
