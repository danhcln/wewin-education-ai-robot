"""Education metadata and queue API inside the existing Control Center."""
import threading
from uuid import uuid4
from fastapi import APIRouter, Request, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .youtube import MediaError
from .asset_service import get_assets

router = APIRouter(prefix='/api/education', tags=['education'])
_queues = {}
_lock = threading.RLock()


def authorized(request, mutate=False):
    from src.api.browser_sessions import get_store
    return get_store().authorize(request, mutating=mutate)


def provider():
    from .routes import youtube
    return youtube


def result(call):
    try:
        return call()
    except MediaError as error:
        raise HTTPException(409, {'code': error.code, 'message': error.message}) from None


def available(video):
    try:
        get_assets().for_video(video['video_id'])
        return {**video, 'playable_on_robot': True}
    except MediaError:
        return {**video, 'playable_on_robot': False, 'source_reason': 'audio_source_unavailable'}


@router.get('/channel')
def channel(request: Request):
    authorized(request)
    return result(lambda: provider().resolve_channel())


@router.get('/lessons')
def lessons(request: Request, query: str = '', limit: int = 5):
    authorized(request)
    def fetch():
        answer = provider().search(query, 'wewin', limit) if query else provider().latest(limit)
        return {**answer, 'videos': [available(v) for v in answer['videos']]}
    return result(fetch)


@router.get('/playlists')
def playlists(request: Request, cursor: str = '', limit: int = 10):
    authorized(request)
    return result(lambda: provider().playlists(cursor, limit))


@router.get('/playlists/{playlist}/items')
def playlist_items(playlist: str, request: Request, cursor: str = '', limit: int = 10):
    authorized(request)
    return result(lambda: provider().playlist_items(playlist, cursor, limit))


class QueueBody(BaseModel):
    model_config = ConfigDict(extra='forbid')
    video_ids: list[str] = Field(min_length=1, max_length=50)


@router.post('/queues')
def queue(body: QueueBody, request: Request):
    owner = authorized(request, True)
    def create():
        p = provider()
        cid = p.resolve_channel()['channel_id']
        rows = [p.video(vid) for vid in body.video_ids]
        if any(v['channel_id'] != cid for v in rows):
            raise MediaError('wrong_channel', 'Bài không thuộc WeWIN Education.')
        with _lock:
            # One bounded queue per principal; no unbounded persistent/global history.
            value = {'queue_id': uuid4().hex, 'revision': 1, 'items': [available(v) for v in rows]}
            _queues[owner] = value
            return value
    return result(create)


@router.get('/queues/current')
def current_queue(request: Request):
    owner = authorized(request)
    with _lock:
        return _queues.get(owner, {'items': [], 'revision': 0})


class Action(BaseModel):
    model_config = ConfigDict(extra='forbid')
    action: str = Field(pattern='^(play|pause|resume|stop|next)$')
    request_id: str = Field(pattern='^[A-Za-z0-9_-]{8,64}$')
    video_id: str | None = None
    queue_revision: int | None = None


@router.post('/playback/actions')
def playback(body: Action, request: Request):
    owner = authorized(request, True)
    from .orchestration import get_session
    with _lock:
        q = _queues.get(owner)
        if body.queue_revision is not None and (not q or q['revision'] != body.queue_revision):
            raise HTTPException(409, 'stale_queue_revision')
        data = body.model_dump(exclude_none=True)
        data['owned_audio'] = True
        if q:
            data['queue'] = [v['video_id'] for v in q['items']]
        return get_session().submit(data)


@router.get('/playback/status')
def playback_status(request: Request):
    authorized(request)
    from .orchestration import get_session
    return get_session().status()


@router.get('/lessons/{vid}')
def lesson(vid: str, request: Request):
    authorized(request)
    def fetch():
        p=provider()
        cid=p.resolve_channel()['channel_id']
        video=p.video(vid)
        if video['channel_id']!=cid:
            raise MediaError('wrong_channel','Bài không thuộc WeWIN Education.')
        return available(video)
    return result(fetch)


class MappingBody(BaseModel):
    model_config=ConfigDict(extra='forbid')
    video_id: str | None = Field(default=None,pattern='^[A-Za-z0-9_-]{11}$')
    expected_revision: int = Field(ge=1)
    content_and_rights_confirmed: bool = False
    revoke: bool = False


@router.get('/assets')
def assets(request: Request):
    authorized(request)
    return {'assets':get_assets().inventory()}


@router.post('/assets/{asset}/mapping')
def mapping(asset: str, body: MappingBody, request: Request):
    authorized(request,True)
    def change():
        if body.video_id:
            p=provider()
            if p.video(body.video_id)['channel_id']!=p.resolve_channel()['channel_id']:
                raise MediaError('wrong_channel','Video không thuộc WeWIN Education.')
        return get_assets().set_mapping(asset,body.video_id,body.expected_revision,
            body.content_and_rights_confirmed,body.revoke)
    return result(change)
