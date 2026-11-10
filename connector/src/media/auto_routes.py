"""Cookie-authenticated browser player + separately authenticated bridge IPC."""
import asyncio
import json
import secrets
from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ConfigDict
from src.api.browser_sessions import COOKIE, OWNER, get_store, same_origin, bridge_key
from src.utils.logger import logger
from .registry import get_registry
from .youtube import MediaError

router=APIRouter(prefix='/api/media/auto')

class Registration(BaseModel):
    model_config=ConfigDict(extra='forbid')
    device_id:str=Field(max_length=64)
    name:str=Field(default='WeWIN Windows Player',max_length=60)

class Tool(BaseModel):
    model_config=ConfigDict(extra='forbid')
    tool:str=Field(max_length=50)
    arguments:dict=Field(default_factory=dict)
    device_id:str|None=Field(default=None,max_length=64)

def dispatch(owner,body):
    from .routes import youtube
    registry=get_registry();name=body.tool;args=body.arguments
    try:
        if name in ('wewin_education_search','wewin_education_browse','wewin_education_playlists'):
            from .education_routes import available
            if name=='wewin_education_playlists':return youtube.playlists(args.get('cursor',''))
            result=youtube.search(args.get('query'),'wewin') if name=='wewin_education_search' else youtube.latest()
            return {**result,'videos':[available(v) for v in result['videos']]}
        if name=='youtube_get_status':
            if args.get('session_id') or args.get('control_token'):raise MediaError('legacy_session_rejected','Xóa quyền phiên cũ khỏi Agent; Auto Player không cần mã thủ công.')
            return registry.status(owner,body.device_id)
        if name=='youtube_control':
            if not args.get('request_id'):
                import uuid
                args['request_id']=uuid.uuid4().hex
            return registry.command(owner,args,youtube,body.device_id)
        if name=='youtube_search':result=youtube.search(args.get('query'),args.get('scope','wewin'),args.get('limit',5))
        elif name=='youtube_list_wewin_videos':result=youtube.latest(args.get('limit',5))
        else:raise MediaError('unknown_tool','Không có công cụ media này.')
        registry.set_queue(owner,result['videos'],body.device_id);return result
    except MediaError as e:return {'status':e.code,'message':e.message}
    except (OSError,ValueError,TypeError,KeyError):return {'status':'media_error','message':'Không xử lý được yêu cầu media.'}

@router.post('/register')
def register(body:Registration,request:Request):
    owner=get_store().authorize(request,True)
    bridge_key(create=True)
    return get_registry().register(owner,body.device_id,body.name)

@router.get('/devices')
def devices(request:Request):return {'devices':get_store().devices(get_store().authorize(request))}

@router.get('/status')
def status(request:Request,device_id:str|None=None):
    try:return get_registry().status(get_store().authorize(request),device_id)
    except MediaError as e:return {'status':e.code,'message':e.message}

@router.post('/default')
def default(body:Registration,request:Request):
    owner=get_store().authorize(request,True);get_store().choose(owner,body.device_id);return {'status':'ok'}

@router.post('/disconnect')
def disconnect(body:Registration,request:Request):
    owner=get_store().authorize(request,True);get_registry().disconnect(owner,body.device_id);return {'status':'ok'}

@router.post('/forget')
def forget(body:Registration,request:Request):
    owner=get_store().authorize(request,True)
    try:get_registry().disconnect(owner,body.device_id,True)
    except MediaError:get_store().forget(owner,body.device_id)
    return {'status':'ok'}

@router.post('/tool')
def tool(body:Tool,request:Request):return dispatch(get_store().authorize(request,True),body)

@router.post('/bridge-tool')
def bridge_tool(body:Tool,request:Request):
    # A browser or public MCP adapter cannot borrow this authority.
    if request.headers.get('origin') or request.headers.get('sec-fetch-site') or request.cookies.get(COOKIE):raise HTTPException(403,'Bridge IPC only.')
    scheme,_,supplied=request.headers.get('authorization','').partition(' ')
    try:expected=bridge_key()
    except (OSError,ValueError):raise HTTPException(503,'Private media bridge is not provisioned.') from None
    if scheme.lower()!='bearer' or not secrets.compare_digest(supplied,expected):raise HTTPException(401,'Invalid bridge authority.')
    if body.device_id is not None:raise HTTPException(422,'Bridge routes only to the selected default player.')
    return dispatch(OWNER,body)

@router.websocket('/player')
async def player(ws:WebSocket):
    entry=cid=None;reason='closed';store=get_store()
    try:
        same_origin(ws)
        if ws.url.query:raise HTTPException(403,'No credentials in URLs.')
        owner=store.authorize(ws)
    except HTTPException:
        await ws.close(code=4401);return
    await ws.accept()
    try:
        raw=await asyncio.wait_for(ws.receive_text(),5)
        if len(raw)>2048:raise MediaError('invalid_auth','Auth frame quá lớn.')
        auth=json.loads(raw)
        if auth.get('type')!='authenticate' or not secrets.compare_digest(str(auth.get('csrf','')),store.csrf(ws.cookies[COOKIE])):
            raise MediaError('unauthorized','Cần phiên trình duyệt hợp lệ.')
        entry,cid=get_registry().connect(owner,auth.get('device_id'),auth.get('tab_id'))
        hub=entry['hub'];pair=entry['pair'];sid=pair['session_id'];token=pair['player_token']
        try:store.choose(owner,auth['device_id'])
        except Exception:pass
        await ws.send_json({'type':'authenticated'})
        while True:
            store.authorize(ws)
            get_store().device(owner,auth['device_id'])
            command=hub.tick(sid,token,cid)
            if command:await ws.send_json(command)
            try:raw=await asyncio.wait_for(ws.receive_text(),.25)
            except asyncio.TimeoutError:continue
            if len(raw)>4096:raise MediaError('invalid_event','Telemetry quá lớn.')
            event=json.loads(raw)
            if not isinstance(event,dict):raise MediaError('invalid_event','Telemetry không hợp lệ.')
            try:hub.event(sid,token,cid,event)
            except MediaError as error:
                if error.code not in ('stale_event','video_mismatch'):raise
    except WebSocketDisconnect as error:reason='transport_'+str(error.code)
    except MediaError as error:
        reason=error.code
        try:await ws.send_json({'type':'connection_error','code':error.code})
        except RuntimeError:pass
        try:await ws.close(code=4409 if error.code=='player_in_use' else 4400)
        except RuntimeError:pass
    except HTTPException:
        reason='authentication_expired'
        try:await ws.close(code=4401)
        except RuntimeError:pass
    except (ValueError,TypeError,KeyError,asyncio.TimeoutError):
        reason='invalid_or_timed_out_frame'
        try:await ws.close(code=4400)
        except RuntimeError:pass
    finally:
        if entry and cid:entry['hub'].disconnect(entry['pair']['session_id'],cid)
        logger.info('Media connection ended: %s',reason)
