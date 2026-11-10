"""Single-process player broker. Bridge relays here over loopback HTTP.

Commands are intentions. Only authenticated IFrame telemetry confirms state.
No knowledge SQLite, durable command replay, or privileged default player.
"""
import hashlib
import re
import secrets
import threading
import time
from uuid import uuid4
from .youtube import MediaError

STATES={'PLAYER_DISCONNECTED','PLAYER_READY','VIDEO_SELECTED','BUFFERING','PLAYING','PAUSED','STOPPED','ENDED','AUTOPLAY_BLOCKED','ERROR'}
EXPECTED={'select':{'VIDEO_SELECTED'},'play':{'PLAYING'},'resume':{'PLAYING'},'pause':{'PAUSED'},'stop':{'STOPPED'},'volume':set()}


class PlayerHub:
    def __init__(self,clock=time.monotonic,heartbeat_timeout=15):
        self.clock=clock;self.lock=threading.RLock();self.session=None
        self.heartbeat_timeout=heartbeat_timeout

    def pair(self):
        with self.lock:
            pt=secrets.token_urlsafe(32);ct=secrets.token_urlsafe(32);sid=uuid4().hex
            self.session={'id':sid,'player_hash':hashlib.sha256(pt.encode()).hexdigest(),
                'control_hash':hashlib.sha256(ct.encode()).hexdigest(),'expires':self.clock()+28800,
                'seen':0,'connection':None,'state':'PLAYER_DISCONNECTED','selected':None,'observed_video_id':None,
                'event_seq':0,'seq':0,'pending':None,'history':{},'recent':[], 'message':''}
            self.session['media_generation']=0
            return {'session_id':sid,'player_token':pt,'control_token':ct,'expires_in_seconds':28800}

    def prune(self):
        with self.lock:
            if self.session and self.session['expires']<=self.clock():self.session=None

    def _auth(self,sid,token,scope='control',connected=False):
        s=self.session
        if not s:raise MediaError('player_disconnected','Chưa có thiết bị phát đang kết nối')
        if s['expires']<=self.clock():
            self.session=None;raise MediaError('session_expired','Phiên đã hết hạn; ghép nối lại player.')
        if sid!=s['id']:raise MediaError('invalid_session','Playback session không hợp lệ.')
        if not isinstance(token,str) or len(token)!=43 or not secrets.compare_digest(hashlib.sha256(token.encode()).hexdigest(),s[scope+'_hash']):
            raise MediaError('unauthorized','Không có quyền với playback session này.')
        if s['connection'] and self.clock()-s['seen']>self.heartbeat_timeout:self._disconnect(s)
        if s['pending'] and self.clock()>s['pending']['deadline']:
            s['pending']['status']='expired';s['pending']=None;s['message']='Player chưa xác nhận lệnh trong thời hạn; không coi là thành công.'
        if connected and not s['connection']:raise MediaError('player_disconnected','Chưa có thiết bị phát đang kết nối')
        return s

    def authorize(self,sid,token):
        with self.lock:self._auth(sid,token,connected=True)

    def connect(self,sid,token):
        with self.lock:
            s=self._auth(sid,token,'player')
            if s['connection']:raise MediaError('player_already_connected','Player này đã có kết nối; ghép lại để thay tab.')
            cid=uuid4().hex;s.update(connection=cid,seen=self.clock(),event_seq=0,state='PLAYER_DISCONNECTED',media_generation=0)
            return cid

    @staticmethod
    def _disconnect(s):
        s['connection']=None;s['state']='PLAYER_DISCONNECTED'
        if s['pending']:s['pending']['status']='disconnected';s['pending']=None

    def disconnect(self,sid,cid):
        with self.lock:
            s=self.session
            if s and s['id']==sid and s['connection']==cid:self._disconnect(s)

    def revoke(self,sid):
        with self.lock:
            if self.session and self.session['id']==sid:self.session=None
        return {'status':'revoked'}

    def snapshot(self,sid=None,token=None):
        with self.lock:
            if not self.session:return {'status':'ok','state':'PLAYER_DISCONNECTED','connected':False,'message':'Chưa có thiết bị phát đang kết nối'}
            s=self._auth(sid,token)
            return {'status':'ok','session_id':s['id'],'state':s['state'] if s['connection'] else 'PLAYER_DISCONNECTED',
                'connected':bool(s['connection']),'selected_video':s['selected'],'observed_video_id':s['observed_video_id'],
                'pending_command':self._receipt(s['pending']) if s['pending'] else None,'message':s['message'],
                'last_command':self._receipt(next(reversed(s['history'].values()))) if s['history'] else None,
                'volume':s.get('volume'),
                'position_seconds':s.get('position_seconds')}

    @staticmethod
    def _receipt(c):
        return {**{k:c[k] for k in ('command_id','request_id','seq','action')},'command_status':c['status']}

    def enqueue(self,sid,token,action,request_id,video=None,volume=None,media_generation=None):
        if action not in EXPECTED:raise MediaError('invalid_action','Thao tác player không hợp lệ.')
        if not isinstance(request_id,str) or not re.fullmatch(r'[A-Za-z0-9_-]{8,64}',request_id):
            raise MediaError('invalid_request_id','Cần request_id riêng; dùng lại cùng mã khi retry đúng một lệnh.')
        if action=='volume' and (type(volume) is not int or not 0<=volume<=100):raise MediaError('invalid_volume','Volume phải từ 0 đến 100.')
        with self.lock:
            s=self._auth(sid,token,connected=True)
            generation=s['media_generation'] if media_generation is None else media_generation
            if type(generation) is not int or generation<0 or generation>2147483647 or generation<s['media_generation']:
                raise MediaError('stale_command','Lệnh thuộc media generation cũ.')
            if generation>s['media_generation']:
                if s['pending']:s['pending']['status']='superseded';s['pending']=None
                s['media_generation']=generation
            signature=(action,video['video_id'] if video else None,volume)
            old=s['history'].get(request_id)
            if old:
                if old['signature']!=signature:raise MediaError('request_conflict','request_id đã được dùng cho nội dung khác.')
                return {'status':'command_'+old['status'],**self._receipt(old),'command_confirmed':old['status']=='confirmed','actual_state':s['state']}
            if s['pending']:raise MediaError('command_pending','Đang chờ player xác nhận lệnh trước; xem trạng thái trước khi gửi tiếp.')
            if s['state']=='PLAYER_DISCONNECTED' or (s['state']=='ERROR' and action!='select'):
                raise MediaError('player_not_ready','Player chưa sẵn sàng; ghép lại hoặc chờ IFrame ready.')
            s['recent']=[t for t in s['recent'] if t>self.clock()-10]
            if len(s['recent'])>=10:raise MediaError('control_rate_limited','Gửi lệnh quá nhanh; chờ trước khi thử lại.')
            if action=='select':
                if not video:raise MediaError('invalid_video_id','Chưa chọn video hợp lệ.')
                s['selected']=video
            elif not s['selected']:raise MediaError('no_video_selected','Chọn video trước khi điều khiển.')
            s['seq']+=1;s['recent'].append(self.clock());s['message']=''
            c={'command_id':uuid4().hex,'request_id':request_id,'seq':s['seq'],'action':action,'status':'queued',
                'signature':signature,'deadline':self.clock()+12,'video_id':s['selected']['video_id'],
                'volume':volume,'sent':False}
            c['media_generation']=generation
            s['history'][request_id]=c;s['pending']=c
            if len(s['history'])>64:del s['history'][next(iter(s['history']))]
            return {'status':'command_queued',**self._receipt(c),'playback_confirmed':False,
                    'message':'Đã xếp lệnh; chưa được IFrame xác nhận.'}

    def tick(self,sid,token,cid):
        with self.lock:
            s=self._auth(sid,token,'player',connected=True)
            if s['connection']!=cid:raise MediaError('invalid_session','Kết nối player đã bị thay thế.')
            c=s['pending']
            if c and not c['sent']:
                c['sent']=True
                return {'type':'command',**self._receipt(c),'video_id':c['video_id'],'volume':c['volume'],
                        'media_generation':c['media_generation'],
                        'expires_at_ms':int(time.time()*1000)+max(0,int((c['deadline']-self.clock())*1000)),
                        'expires_in_ms':max(0,int((c['deadline']-self.clock())*1000))}
            return None

    def event(self,sid,token,cid,event):
        with self.lock:
            s=self._auth(sid,token,'player',connected=True)
            if s['connection']!=cid:raise MediaError('invalid_session','Kết nối không hợp lệ.')
            s['seen']=self.clock()
            if event.get('type')=='heartbeat':return
            if s['media_generation'] and event.get('media_generation')!=s['media_generation']:
                raise MediaError('stale_event','ACK thuộc media generation cũ.')
            seq=event.get('event_seq')
            if type(seq) is not int or seq<=s['event_seq']:raise MediaError('stale_event','Bỏ qua telemetry cũ/trùng.')
            s['event_seq']=seq;c=s['pending']
            if event.get('type')=='received':
                if c and event.get('command_id')==c['command_id']:c['status']='received'
                return
            state=event.get('state')
            if state not in STATES:raise MediaError('invalid_state','Trạng thái player không hợp lệ.')
            observed=event.get('video_id')
            if observed and s['selected'] and observed!=s['selected']['video_id']:
                if s['media_generation'] and (not c or c['action']!='select'):
                    s['state']='ERROR';s['message']='Browser đang phát nguồn khác với MediaSession.'
                raise MediaError('video_mismatch','Telemetry thuộc video khác; không xác nhận lệnh.')
            if state in ('PLAYING','PAUSED','BUFFERING','VIDEO_SELECTED','ENDED','STOPPED') and (not s['selected'] or observed!=s['selected']['video_id']):
                raise MediaError('video_mismatch','Thiếu video ID thật từ IFrame.')
            s['state']=state;s['observed_video_id']=observed
            if type(event.get('volume')) is int and 0<=event['volume']<=100:s['volume']=event['volume']
            position=event.get('current_time')
            if type(position) in (int,float) and 0<=position<=86400:s['position_seconds']=round(position,2)
            s['message']={'AUTOPLAY_BLOCKED':'Trình duyệt chặn autoplay. Bấm Play trực tiếp trong khung YouTube.',
                          'ERROR':'YouTube Player không phát được video. Kiểm tra lỗi nhúng/khả dụng.'}.get(state,'')
            if state=='ERROR':
                s['message']={2:'Video ID/tham số player không hợp lệ.',5:'YouTube HTML5 Player không phát được nội dung.',
                    100:'Video không tồn tại, đã bị xóa hoặc không công khai.',101:'Chủ video không cho phép nhúng.',
                    150:'Chủ video không cho phép nhúng.',153:'YouTube từ chối danh tính embed/referrer. Mở từ localhost và kiểm tra chính sách referrer.'}.get(event.get('error_code'),s['message'])
            if c and event.get('command_id')==c['command_id']:
                if state in ('ERROR','AUTOPLAY_BLOCKED'):c['status']='failed';s['pending']=None
                elif state in EXPECTED[c['action']] or (c['action']=='volume' and event.get('volume')==c['volume']):
                    c['status']='confirmed';s['pending']=None
