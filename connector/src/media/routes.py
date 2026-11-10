import asyncio
import json
from typing import Any
from urllib.parse import urlsplit
from fastapi import APIRouter, Depends, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field, ConfigDict
from src.api.security import verify_admin_token
from src.mcp.bridge_status import read_status
from .hub import PlayerHub
from .youtube import YouTubeClient, MediaError

router=APIRouter(prefix='/api/media')
hub=PlayerHub()
youtube=YouTubeClient()

async def expire_media_cache():
    while True:
        await asyncio.to_thread(youtube.prune)
        hub.prune()
        await asyncio.sleep(60)

class ToolRequest(BaseModel):
    model_config=ConfigDict(extra='forbid')
    tool:str=Field(max_length=50)
    arguments:dict[str,Any]=Field(default_factory=dict)

class RevokeRequest(BaseModel):
    session_id:str=Field(max_length=64)

def handle_media_tool(name,args):
    try:
        if not isinstance(args,dict) or len(args)>8:raise MediaError('invalid_arguments','arguments không hợp lệ.')
        if name=='youtube_search':return youtube.search(args.get('query'),args.get('scope','wewin'),args.get('limit',5))
        if name=='youtube_list_wewin_videos':return youtube.latest(args.get('limit',5))
        if name=='youtube_get_status':return hub.snapshot(args.get('session_id'),args.get('control_token'))
        if name=='youtube_control':
            sid=args.get('session_id');token=args.get('control_token');action=args.get('action')
            hub.authorize(sid,token)
            video=youtube.video(args.get('video_id')) if action=='select' else None
            return hub.enqueue(sid,token,action,args.get('request_id'),video,args.get('volume'))
        raise MediaError('unknown_tool','Không có công cụ media này.')
    except MediaError as e:return {'status':e.code,'message':e.message}
    except (OSError,ValueError,KeyError,TypeError):return {'status':'media_error','message':'Không xử lý được media trong giới hạn an toàn.'}

@router.get('/config')
def config():
    import time
    configured=bool(youtube.key_provider())
    channel=youtube.channel if configured and youtube.channel and time.time()-youtube.channel['verified_at']<86400 else None
    return {'api_key_configured':configured,'handle':'@WeWINEducation',
            'channel':channel,'mcp_status':read_status(),'single_player':True,'test_fixture':bool(getattr(youtube,'is_fixture',False))}

@router.post('/pair',dependencies=[Depends(verify_admin_token)])
def pair():return hub.pair()

@router.post('/revoke',dependencies=[Depends(verify_admin_token)])
def revoke(body:RevokeRequest):return hub.revoke(body.session_id)

@router.post('/tool')
def tool(body:ToolRequest):return handle_media_tool(body.tool,body.arguments)

@router.websocket('/player')
async def player(ws:WebSocket):
    origin=urlsplit(ws.headers.get('origin',''))
    if origin.scheme not in ('http','https') or origin.netloc!=ws.headers.get('host') or ws.url.query:
        await ws.close(code=1008);return
    await ws.accept();sid=cid=token=None
    try:
        raw=await asyncio.wait_for(ws.receive_text(),5)
        if len(raw)>2048:raise MediaError('invalid_auth','Auth frame quá lớn.')
        auth=json.loads(raw)
        if auth.get('type')!='authenticate':raise MediaError('unauthorized','Cần ghép nối player.')
        sid=auth.get('session_id');token=auth.get('player_token');cid=hub.connect(sid,token)
        await ws.send_json({'type':'authenticated'})
        while True:
            command=hub.tick(sid,token,cid)
            if command:await ws.send_json(command)
            try:raw=await asyncio.wait_for(ws.receive_text(),.25)
            except asyncio.TimeoutError:continue
            if len(raw)>4096:raise MediaError('invalid_event','Telemetry quá lớn.')
            event=json.loads(raw)
            if not isinstance(event,dict):raise MediaError('invalid_event','Telemetry không hợp lệ.')
            try:hub.event(sid,token,cid,event)
            except MediaError as e:
                if e.code not in ('stale_event','video_mismatch'):raise
                await ws.send_json({'type':'event_rejected','code':e.code})
    except (WebSocketDisconnect,asyncio.TimeoutError,MediaError,ValueError,TypeError,AttributeError):
        try:await ws.close(code=1008)
        except RuntimeError:pass
    finally:
        if sid and cid:hub.disconnect(sid,cid)
