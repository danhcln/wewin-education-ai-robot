"""Owner-scoped default players. Credentials stay inside the backend process."""
import hashlib
import json
import re
import threading
import time
from uuid import UUID
from fastapi import HTTPException
from src.api.browser_sessions import get_store
from .hub import PlayerHub
from .youtube import MediaError

class PlayerRegistry:
    def __init__(self,store=None,clock=time.monotonic):
        self.store=store or get_store();self.clock=clock;self.lock=threading.RLock();self.players={};self.queues={}

    def register(self,owner,device,name):
        try:UUID(device)
        except (ValueError,TypeError,AttributeError):raise HTTPException(422,'Invalid device identifier.') from None
        if not isinstance(name,str) or not 1<=len(name.strip())<=60 or any(ord(x)<32 for x in name):raise HTTPException(422,'Invalid player name.')
        record=self.store.register_device(owner,device,name.strip())
        if not self.store.default(owner):self.store.choose(owner,device)
        with self.lock:
            key=(owner,device);entry=self.players.get(key)
            if not entry or not entry['hub'].session or entry['hub'].session['expires']<=self.clock():
                hub=PlayerHub(self.clock,heartbeat_timeout=30);pair=hub.pair()
                entry={'hub':hub,'pair':pair,'epoch':pair['session_id'],'tab':None};self.players[key]=entry
        return {'device_id':device,'name':record['name'],'is_default':bool(self.store.device(owner,device)['is_default']),
                'heartbeat_seconds':5,'heartbeat_timeout_seconds':30,'session_credentials_in_browser':False}

    def entry(self,owner,device):
        self.store.device(owner,device)
        entry=self.players.get((owner,device))
        if not entry:raise MediaError('player_disconnected','Chưa có thiết bị phát đang kết nối. Hãy mở Media Player.')
        return entry

    def connect(self,owner,device,tab):
        if not isinstance(tab,str) or not re.fullmatch('[a-zA-Z0-9_-]{16,64}',tab):raise MediaError('invalid_tab','Tab identifier không hợp lệ.')
        with self.lock:
            e=self.entry(owner,device);p=e['pair'];snapshot=e['hub'].snapshot(p['session_id'],p['control_token'])
            if snapshot['connected']:raise MediaError('player_in_use','Player đang hoạt động ở tab khác. Chỉ một tab nhận lệnh.')
            cid=e['hub'].connect(p['session_id'],p['player_token']);e['tab']=tab
            return e,cid

    def status(self,owner,device=None):
        if device is None:
            default=self.store.default(owner)
            device=default['device'] if default else None
            if not device or (owner, device) not in self.players or not self.players[(owner, device)]['hub'].session or not self.players[(owner, device)]['hub'].session.get('connection'):
                for (p_owner, p_device), p_entry in self.players.items():
                    if p_owner == owner and p_entry.get('hub') and p_entry['hub'].session and p_entry['hub'].session.get('connection'):
                        device = p_device
                        break
            if not device:
                return {'status':'ok','state':'PLAYER_DISCONNECTED','connected':False,'message':'Chưa có thiết bị phát đang kết nối. Hãy mở Media Player.'}
        record=self.store.device(owner,device);e=self.players.get((owner,device))
        if not e:result={'status':'ok','state':'PLAYER_DISCONNECTED','connected':False}
        else:
            try:result=e['hub'].snapshot(e['pair']['session_id'],e['pair']['control_token'])
            except MediaError:result={'status':'ok','state':'PLAYER_DISCONNECTED','connected':False,'reason':'session_expired'}
        return {k:v for k,v in {**result,'device_id':device,'name':record['name'],'is_default':bool(record['is_default'])}.items() if k!='session_id'}

    def disconnect(self,owner,device,forget=False):
        with self.lock:
            e=self.entry(owner,device)
            with e['hub'].lock:
                if e['hub'].session:e['hub']._disconnect(e['hub'].session)
            if forget:
                e['hub'].revoke(e['pair']['session_id']);self.players.pop((owner,device),None);self.store.forget(owner,device)

    def set_queue(self,owner,videos,device=None):
        default=self.store.default(owner)
        device=device or (default['device'] if default else None)
        if device:self.queues[(owner,device)]=[v['video_id'] for v in videos[:10]]

    def command(self,owner,args,youtube,device=None,wait_seconds=5):
        if not isinstance(args,dict) or len(args)>8:raise MediaError('invalid_arguments','Tham số điều khiển không hợp lệ.')
        # Legacy capabilities must never silently retarget a newer default player.
        if args.get('session_id') or args.get('control_token'):
            raise MediaError('legacy_session_rejected','Xóa quyền phiên cũ khỏi Agent. Auto Player không nhận mã phiên thủ công.')
        default=self.store.default(owner)
        device=device or (default['device'] if default else None)
        if not device or (owner, device) not in self.players or not self.players[(owner, device)]['hub'].session or not self.players[(owner, device)]['hub'].session.get('connection'):
            for (p_owner, p_device), p_entry in self.players.items():
                if p_owner == owner and p_entry.get('hub') and p_entry['hub'].session and p_entry['hub'].session.get('connection'):
                    device = p_device
                    try:self.store.choose(owner, device)
                    except Exception:pass
                    break
        if not device:raise MediaError('player_disconnected','Chưa có thiết bị phát đang kết nối. Hãy mở Media Player.')
        e=self.entry(owner,device);hub=e['hub'];pair=e['pair'];sid=pair['session_id'];cap=pair['control_token']
        hub.authorize(sid,cap)
        rid=args.get('request_id');action=args.get('action')
        if not rid:
            import uuid; rid=uuid.uuid4().hex; args['request_id']=rid
        if not isinstance(rid,str) or not re.fullmatch('[a-zA-Z0-9_-]{8,64}',rid):raise MediaError('invalid_request_id','Cần request_id mới cho mỗi ý định.')
        if action not in ('select','play','pause','resume','stop','volume','first','next','latest'):
            raise MediaError('invalid_action','Thao tác không hợp lệ.')
        signature=json.dumps(args,sort_keys=True,ensure_ascii=True)
        with self.lock:
            old=self.store.claim_intent(owner,rid,device,e['epoch'],signature)
            if old:
                if old['device']!=device or old['epoch']!=e['epoch']:
                    raise MediaError('stale_command','Không phát lại lệnh thuộc phiên/backend cũ. Hãy gửi ý định mới.')
                if old['signature']!=signature:raise MediaError('request_conflict','request_id đã dùng cho tham số khác.')
                # Do not re-resolve "next" against a changed queue on retry.
                return {**self.status(owner,device),'status':'duplicate_request','message':'Lệnh đã được nhận; không phát lại. Xem trạng thái thực tế.'}
        def send(step,vid=None):
            step_id=hashlib.sha256((rid+':'+step).encode()).hexdigest()[:32]
            video=youtube.video(vid) if step=='select' else None
            receipt=hub.enqueue(sid,cap,step,step_id,video,args.get('volume'),args.get('media_generation'))
            until=time.monotonic()+wait_seconds
            while time.monotonic()<until:
                snapshot=self.status(owner,device)
                if not snapshot['connected']:raise MediaError('player_disconnected','Player đã mất kết nối; chưa có xác nhận lệnh.')
                last=snapshot.get('last_command')
                if last and last['request_id']==step_id and last['command_status']=='confirmed':
                    return {**snapshot,'status':'command_confirmed','command_confirmed':True}
                if snapshot['state'] in ('ERROR','AUTOPLAY_BLOCKED'):
                    return {**snapshot,'status':'autoplay_blocked' if snapshot['state']=='AUTOPLAY_BLOCKED' else 'player_error'}
                time.sleep(.1)
            return {**receipt,**self.status(owner,device),'status':'command_pending','command_confirmed':False}
        if action in ('first','next','latest') or (action=='play' and not args.get('video_id') and not self.status(owner,device).get('selected_video')):
            if action=='latest':self.set_queue(owner,youtube.latest(5)['videos'],device)
            queue=self.queues.get((owner,device),[])
            if not queue:
                self.set_queue(owner,youtube.latest(5)['videos'],device)
                queue=self.queues.get((owner,device),[])
            if not queue:raise MediaError('empty_queue','Chưa có danh sách video. Hãy tìm video trước.')
            target=queue[0]
            if action=='next':
                current=self.status(owner,device).get('selected_video',{}).get('video_id')
                if current not in queue or queue.index(current)+1>=len(queue):raise MediaError('no_next_video','Không có video tiếp theo trong danh sách hiện tại.')
                target=queue[queue.index(current)+1]
            selected=send('select',target)
            if selected['status']!='command_confirmed':return selected
            return send('play')
        return send(action,args.get('video_id'))

_registries={}
_registry_lock=threading.RLock()
def get_registry():
    store=get_store();key=str(store.path)
    with _registry_lock:
        if key not in _registries:_registries[key]=PlayerRegistry(store)
        return _registries[key]
