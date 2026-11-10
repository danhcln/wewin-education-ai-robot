"""Official YouTube Data API v3 only. Credentials never enter URLs/results."""
from collections import Counter, deque
import html
import json
import os
from pathlib import Path
import re
import threading
import time
import tempfile
import httpx
from src.config import BASE_DIR

HANDLE='@WeWINEducation'
VIDEO_RE=re.compile(r'^[A-Za-z0-9_-]{11}$')
CHANNEL_RE=re.compile(r'^UC[A-Za-z0-9_-]{22}$')


class MediaError(Exception):
    def __init__(self,code,message):
        super().__init__(message);self.code=code;self.message=message


def video_id(value):
    if not isinstance(value,str) or not VIDEO_RE.fullmatch(value):
        raise MediaError('invalid_video_id','Video ID phải có đúng 11 ký tự hợp lệ, không nhận URL hoặc lệnh máy tính.')
    return value


def api_key():
    value=os.getenv('YOUTUBE_API_KEY','').strip()
    if not value:
        path=Path(os.getenv('YOUTUBE_API_KEY_FILE') or BASE_DIR/'.secrets/youtube/api_key')
        try:
            if path.stat().st_size>1024:return ''
            value=path.read_text(encoding='utf-8').strip()
        except (OSError,UnicodeError):return ''
    return value if re.fullmatch(r'[A-Za-z0-9_-]{20,256}',value) else ''


class YouTubeClient:
    def __init__(self,key_provider=api_key,http=None,clock=time.monotonic,sleep=time.sleep,channel_file=None):
        self.key_provider=key_provider;self.http=http or httpx.Client(timeout=4,follow_redirects=False,trust_env=False)
        self.clock=clock;self.sleep=sleep;self.lock=threading.RLock();self.cache={};self.calls=Counter()
        self.last=None;self.search_calls=deque();self.blocked_until=0;self.channel=None
        self.channel_file=Path(channel_file or os.getenv('YOUTUBE_CHANNEL_FILE') or BASE_DIR/'.maintenance/media/youtube_channel.json')
        target=self.channel_file.resolve()
        self.storage_valid=target.suffix=='.json' and not target.is_relative_to(BASE_DIR/'data') and not target.is_relative_to(BASE_DIR/'frontend')

    def prune(self):
        """Expiry cleanup only. Never calls Google, crawls, or touches knowledge DB."""
        with self.lock:
            self.cache={k:v for k,v in self.cache.items() if v[0]>self.clock()}
            if self.channel and time.time()-self.channel['verified_at']>=86400:self.channel=None
            if not self.storage_valid:return
            try:
                if self.channel_file.stat().st_size>4096:return
                record=json.loads(self.channel_file.read_text(encoding='utf-8'))
                if record.get('method')=='channels.list(forHandle)' and record.get('handle')==HANDLE and type(record.get('verified_at')) in (int,float) and time.time()-record['verified_at']>=86400:
                    self.channel_file.unlink()
            except (OSError,ValueError,TypeError,AttributeError):pass

    def _store_channel(self,record):
        if not self.storage_valid:raise MediaError('invalid_channel_storage','Channel metadata phải ở file JSON riêng ngoài data và webroot.')
        if self.channel_file.exists():
            try:
                old=json.loads(self.channel_file.read_text(encoding='utf-8'))
                if old.get('method')!='channels.list(forHandle)' or old.get('handle')!=HANDLE:raise ValueError()
            except (ValueError,AttributeError):
                raise MediaError('channel_storage_conflict','Không ghi đè file cấu hình không thuộc bộ cache YouTube.') from None
        self.channel_file.parent.mkdir(mode=0o700,parents=True,exist_ok=True)
        fd,name=tempfile.mkstemp(prefix='channel-',suffix='.tmp',dir=self.channel_file.parent)
        try:
            with os.fdopen(fd,'w',encoding='utf-8') as f:json.dump(record,f,ensure_ascii=False)
            os.chmod(name,0o600);os.replace(name,self.channel_file)
        finally:
            if Path(name).exists():Path(name).unlink()

    def _cached(self,key,action,ttl=300):
        with self.lock:
            if not self.key_provider():raise MediaError('api_key_missing','Chưa cấu hình YouTube API key; không báo kết quả live giả.')
            now=self.clock();entry=self.cache.get(key)
            if entry and entry[0]>now:return entry[1]
            result=action()
            self.cache={k:v for k,v in self.cache.items() if v[0]>now}
            if len(self.cache)>=128:self.cache.pop(next(iter(self.cache)))
            self.cache[key]=(now+ttl,result)
            return result

    def _request(self,resource,params):
        return self._request_page(resource,params)["items"]

    def _request_page(self,resource,params):
        key=self.key_provider()
        if not key:raise MediaError('api_key_missing','Chưa cấu hình YouTube API key; chưa thể tìm kiếm live hoặc xác minh kênh.')
        if self.clock()<self.blocked_until:raise MediaError('quota_or_rate_limited','YouTube đang giới hạn truy cập; thử lại sau, kiểm tra quota trong Google Cloud.')
        now=self.clock()
        while self.search_calls and self.search_calls[0]<=now-86400:self.search_calls.popleft()
        if resource=='search' and len(self.search_calls)>=40:
            raise MediaError('local_quota_limit','Đã đạt ngân sách cục bộ 40 search request/24 giờ của process này.')
        for attempt in range(3):
            if resource=='search':
                if len(self.search_calls)>=40:raise MediaError('local_quota_limit','Đã đạt ngân sách search cục bộ.')
                self.search_calls.append(self.clock())
            if self.last is not None:self.sleep(max(0,1-(self.clock()-self.last)))
            self.last=self.clock();self.calls[resource]+=1
            try:
                response=self.http.get('https://www.googleapis.com/youtube/v3/'+resource,params=params,
                                       headers={'X-Goog-Api-Key':key,'Accept':'application/json'})
                if len(response.content)>1048576:raise MediaError('api_response_invalid','Phản hồi API quá lớn.')
                if response.status_code==200:
                    data=response.json()
                    if not isinstance(data,dict) or not isinstance(data.get('items'),list):raise ValueError()
                    return data
                reason=''
                try:reason=response.json().get('error',{}).get('errors',[{}])[0].get('reason','')
                except (ValueError,TypeError,IndexError,AttributeError):pass
                if reason in ('quotaExceeded','dailyLimitExceeded'):
                    self.blocked_until=self.clock()+300
                    raise MediaError('quota_exceeded','YouTube quota đã hết; kiểm tra Google Cloud Console. Không trả kết quả giả.')
                if response.status_code in (400,401,403):
                    raise MediaError('api_access_denied','YouTube từ chối API key/quyền truy cập; kiểm tra key restriction và API đã bật.')
                if response.status_code not in (429,500,502,503,504):
                    raise MediaError('youtube_api_error','YouTube API không trả dữ liệu hợp lệ.')
                retry=response.headers.get('retry-after','0')
                try:wait=max(.5*(2**attempt),float(retry))
                except ValueError:
                    from email.utils import parsedate_to_datetime
                    from datetime import datetime, timezone
                    try:wait=max(.5*(2**attempt),(parsedate_to_datetime(retry)-datetime.now(timezone.utc)).total_seconds())
                    except (ValueError,TypeError,OverflowError):wait=2
                if wait>4 or attempt==2:
                    self.blocked_until=self.clock()+max(10,wait)
                    raise MediaError('quota_or_rate_limited','YouTube đang bận hoặc giới hạn tốc độ; chưa tiếp tục request.')
                self.sleep(wait)
            except httpx.RequestError:
                if attempt==2:raise MediaError('youtube_timeout','Không kết nối được YouTube trong thời gian cho phép.') from None
                self.sleep(.5*(2**attempt))
            except (ValueError,KeyError,TypeError):
                raise MediaError('api_response_invalid','Không đọc được metadata từ YouTube API.') from None
        raise MediaError('youtube_api_error','YouTube API không khả dụng.')

    def resolve_channel(self):
        def fetch():
            self.channel=None
            items=self._request('channels',{'part':'snippet,contentDetails','forHandle':HANDLE})
            if len(items)!=1:raise MediaError('channel_unverified','Chưa xác minh được kênh @WeWINEducation bằng channels.list.')
            item=items[0];cid=item.get('id','');uploads=item.get('contentDetails',{}).get('relatedPlaylists',{}).get('uploads','')
            if not CHANNEL_RE.fullmatch(cid) or not re.fullmatch(r'[A-Za-z0-9_-]{16,64}',uploads):
                raise MediaError('channel_unverified','YouTube không trả Channel ID/Uploads Playlist ID hợp lệ.')
            custom=item.get('snippet',{}).get('customUrl')
            if custom and custom.lstrip('@').casefold()!=HANDLE.lstrip('@').casefold():
                raise MediaError('channel_unverified','Handle trả về không khớp kênh WeWIN được chỉ định.')
            channel={'handle':HANDLE,'channel_id':cid,'uploads_playlist_id':uploads,'title':item.get('snippet',{}).get('title',''),
                     'verified':True,'verified_at':time.time(),'method':'channels.list(forHandle)'}
            self.channel=channel
            # Only persist identifiers from an actual API response; never derive IDs.
            self._store_channel(channel)
            return channel
        return self._cached(('channel',),fetch,86400)

    def _videos(self,ids):
        if not ids:return []
        ids=list(dict.fromkeys(video_id(v) for v in ids))[:10]
        def fetch():
            items=self._request('videos',{'part':'snippet,status,contentDetails','id':','.join(ids)})
            videos=[]
            verified=self.channel['channel_id'] if self.channel else None
            for row in items:
                vid=row.get('id');snippet=row.get('snippet',{});status=row.get('status',{})
                if vid not in ids:continue
                cid=snippet.get('channelId','')
                if not CHANNEL_RE.fullmatch(cid):continue
                thumb=snippet.get('thumbnails',{}).get('medium',{}).get('url','')
                from urllib.parse import urlsplit
                u=urlsplit(thumb)
                if u.scheme!='https' or u.hostname!='i.ytimg.com' or u.username:thumb=''
                available=status.get('embeddable') is True and status.get('privacyStatus')=='public' and status.get('uploadStatus')=='processed'
                videos.append({'video_id':vid,'title':html.unescape(str(snippet.get('title','')))[:300],'channel_id':cid,
                    'channel_title':str(snippet.get('channelTitle',''))[:200],'thumbnail':thumb,
                    'published_at':snippet.get('publishedAt'),'url':'https://www.youtube.com/watch?v='+vid,
                    'is_wewin':bool(verified and cid==verified),'availability':'embed_eligible_not_playback_confirmed' if available else 'unavailable_or_not_embeddable',
                    'embeddable':available,'region_restriction':row.get('contentDetails',{}).get('regionRestriction')})
            order={v:i for i,v in enumerate(ids)}
            return sorted(videos,key=lambda v:order[v['video_id']])
        result=self._cached(('videos',tuple(ids)),fetch)
        verified=self.channel['channel_id'] if self.channel else None
        return [{**v,'is_wewin':bool(verified and v['channel_id']==verified)} for v in result]

    def video(self,vid):
        rows=self._videos([video_id(vid)])
        if not rows:raise MediaError('video_not_found','Video không tồn tại hoặc không truy xuất được qua API.')
        if not rows[0]['embeddable']:raise MediaError('video_unavailable','Video không công khai hoặc không cho phép nhúng.')
        return rows[0]

    def search(self,query,scope='wewin',limit=5):
        if scope not in ('wewin','all') or not isinstance(query,str) or not 1<=len(query.strip())<=160 or type(limit) is not int or not 1<=limit<=10:
            raise MediaError('invalid_arguments','Từ khóa/scope/limit không hợp lệ.')
        channel=self.resolve_channel() if scope=='wewin' else None
        def fetch():
            params={'part':'snippet','q':query.strip(),'type':'video','maxResults':limit,'videoEmbeddable':'true','safeSearch':'strict'}
            if channel:params['channelId']=channel['channel_id']
            rows=self._request('search',params)
            ids=[r.get('id',{}).get('videoId','') for r in rows]
            videos=self._videos([v for v in ids if VIDEO_RE.fullmatch(v)])
            if channel:videos=[v for v in videos if v['channel_id']==channel['channel_id']]
            return {'status':'ok','videos':videos,'scope':scope,'channel':channel}
        result=self._cached(('search',query.strip(),scope,limit,channel['channel_id'] if channel else None),fetch)
        verified=self.channel['channel_id'] if self.channel else None
        return {**result,'videos':[{**v,'is_wewin':bool(verified and v['channel_id']==verified)} for v in result['videos']]}

    def latest(self,limit=5):
        if type(limit) is not int or not 1<=limit<=10:raise MediaError('invalid_arguments','limit phải từ 1 đến 10.')
        channel=self.resolve_channel()
        def fetch():
            rows=self._request('playlistItems',{'part':'contentDetails','playlistId':channel['uploads_playlist_id'],'maxResults':limit})
            ids=[r.get('contentDetails',{}).get('videoId','') for r in rows]
            videos=self._videos([v for v in ids if VIDEO_RE.fullmatch(v)])
            return {'status':'ok','videos':[v for v in videos if v['channel_id']==channel['channel_id']], 'channel':channel}
        return self._cached(('latest',limit,channel['channel_id'],channel['uploads_playlist_id']),fetch)


    def playlists(self, cursor='', limit=10):
        channel=self.resolve_channel()
        return self._catalog_page('playlists',{'part':'snippet,contentDetails','channelId':channel['channel_id']},cursor,limit)

    def playlist_items(self, playlist, cursor='', limit=10):
        if not isinstance(playlist,str) or not re.fullmatch(r'[A-Za-z0-9_-]{16,64}',playlist):
            raise MediaError('invalid_playlist','Playlist không hợp lệ.')
        channel=self.resolve_channel()
        rows=self._cached(('playlist-owner',playlist),lambda:self._request('playlists',{'part':'snippet','id':playlist}))
        if len(rows)!=1 or rows[0].get('snippet',{}).get('channelId')!=channel['channel_id']:
            raise MediaError('wrong_channel','Playlist không thuộc kênh WeWIN.')
        return self._catalog_page('playlistItems',{'part':'snippet,contentDetails','playlistId':playlist},cursor,limit)

    def _catalog_page(self, resource, params, cursor, limit):
        if type(limit) is not int or not 1<=limit<=20 or not isinstance(cursor,str) or len(cursor)>256 or not re.fullmatch(r'[A-Za-z0-9_=-]*',cursor):
            raise MediaError('invalid_arguments','Phân trang không hợp lệ.')
        params={**params,'maxResults':limit}
        if cursor:params['pageToken']=cursor
        page=self._cached(('catalog',resource,tuple(sorted(params.items()))),lambda:self._request_page(resource,params))
        rows=[]
        for row in page['items']:
            snippet=row.get('snippet',{})
            if resource=='playlists':
                rows.append({'playlist_id':row['id'],'title':str(snippet.get('title',''))[:300]})
            else:
                vid=row.get('contentDetails',{}).get('videoId','')
                if not VIDEO_RE.fullmatch(vid):continue
                try:video=self.video(vid)
                except MediaError as error:
                    if error.code not in ('video_not_found','video_unavailable'):raise
                    rows.append({'video_id':vid,'availability':'unavailable','position':snippet.get('position')});continue
                if video['channel_id']==self.channel['channel_id']:
                    rows.append({**video,'position':snippet.get('position')})
        return {'items':rows,'next_cursor':page.get('nextPageToken'),'channel':self.channel}
