"""Bridge/API processes share a player through authenticated loopback commands."""
import os
from urllib.parse import urlsplit
import httpx

MEDIA_NAMES={'youtube_search','youtube_list_wewin_videos','youtube_control','youtube_get_status'}
def schema(p,r):return {'type':'object','properties':p,'required':r,'additionalProperties':False}
SESSION={'type':'string','description':'Chỉ cho API legacy; KHÔNG truyền trường này khi dùng Cloud Auto Player.'}
CAP={'type':'string','description':'Chỉ cho API legacy; KHÔNG truyền trường này khi dùng Cloud Auto Player. Không đọc mã thành tiếng.'}
MEDIA_DEFINITIONS=[
 {'name':'youtube_search','description':'Tìm kiếm video trên kênh YouTube chính thức của WeWIN Education (@WeWINEducation) hoặc toàn YouTube. BẮT BUỘC gọi khi người dùng yêu cầu: tìm video về..., xem video về..., WeWIN có video nào về... query là từ khóa tìm kiếm tiếng Việt hoặc tiếng Anh.',
  'inputSchema':schema({'query':{'type':'string','minLength':1,'maxLength':160,'description':'Từ khóa tìm kiếm video'},'scope':{'type':'string','enum':['wewin','all'],'default':'wewin'},'limit':{'type':'integer','minimum':1,'maximum':10,'default':5}},['query'])},
 {'name':'youtube_list_wewin_videos','description':'Lấy danh sách các video mới nhất từ kênh YouTube chính thức của WeWIN Education (@WeWINEducation). BẮT BUỘC gọi khi người dùng hỏi: WeWIN có những video gì, danh sách video của WeWIN, xem các video mới nhất của WeWIN.',
  'inputSchema':schema({'limit':{'type':'integer','minimum':1,'maximum':10,'default':5}},[])},
 {'name':'youtube_control','description':'Điều khiển trình phát video YouTube WeWIN Education trên màn hình laptop/Web. BẮT BUỘC gọi khi người dùng yêu cầu: phát video mới nhất (action=latest), phát video (action=play), tạm dừng video (action=pause), tiếp tục phát (action=resume), chuyển sang video tiếp theo (action=next), dừng phát hẳn (action=stop), hoặc chỉnh âm lượng (action=volume, volume=0-100).',
  'inputSchema':schema({'action':{'type':'string','enum':['latest','play','pause','resume','next','stop','select','first','volume'],'description':'Hành động điều khiển: latest (phát mới nhất), play (phát), pause (tạm dừng), resume (tiếp tục), next (video tiếp theo), stop (dừng hẳn)'},'video_id':{'type':'string','pattern':'^[A-Za-z0-9_-]{11}$','description':'Mã video 11 ký tự nếu chọn video cụ thể'},'volume':{'type':'integer','minimum':0,'maximum':100,'description':'Mức âm lượng từ 0 đến 100'},'request_id':{'type':'string','description':'Mã định danh yêu cầu (tùy chọn)'}},['action'])},
 {'name':'youtube_get_status','description':'Xem trạng thái phát video hiện tại của trình phát trên màn hình máy tính (đang phát, tạm dừng, video nào, âm lượng).',
  'inputSchema':schema({},[])}]

def relay_media_tool(name,args):
    base=(os.getenv('MEDIA_BACKEND_URL') or 'http://127.0.0.1:8000').rstrip('/')
    try:
        p=urlsplit(base)
        if p.scheme!='http' or p.hostname!='127.0.0.1' or p.username or p.password or p.path or p.query or p.fragment:
            return {'status':'invalid_backend','message':'MEDIA_BACKEND_URL chỉ cho HTTP loopback 127.0.0.1:cổng.'}
        with httpx.Client(timeout=20,trust_env=False,follow_redirects=False) as client:
            response=client.post(base+'/api/media/tool',json={'tool':name,'arguments':args})
        if response.status_code!=200:return {'status':'backend_rejected','message':'Backend từ chối yêu cầu media.'}
        data=response.json()
        return data if isinstance(data,dict) else {'status':'backend_error','message':'Phản hồi media không hợp lệ.'}
    except (httpx.HTTPError,ValueError):
        return {'status':'backend_unavailable','message':'Chưa kết nối được FastAPI Media Backend trên localhost. Không có xác nhận phát.'}


def relay_cloud_media_tool(name,args):
    """Called only by the authenticated Cloud bridge, never the public dispatcher."""
    from src.api.browser_sessions import bridge_key
    base=(os.getenv('MEDIA_BACKEND_URL') or 'http://127.0.0.1:8000').rstrip('/')
    try:
        p=urlsplit(base)
        if p.scheme!='http' or p.hostname!='127.0.0.1' or p.username or p.password or p.path or p.query or p.fragment:
            return {'status':'invalid_backend','message':'Media bridge chỉ dùng HTTP loopback.'}
        key=bridge_key(create=True)
        with httpx.Client(timeout=40,trust_env=False,follow_redirects=False) as client:
            response=client.post(base+'/api/media/auto/bridge-tool',json={'tool':name,'arguments':args},headers={'Authorization':'Bearer '+key})
        if response.status_code!=200:return {'status':'backend_rejected','message':'Backend từ chối quyền bridge hoặc yêu cầu media.'}
        data=response.json()
        return data if isinstance(data,dict) else {'status':'backend_error','message':'Phản hồi không hợp lệ.'}
    except (OSError,httpx.HTTPError,ValueError):return {'status':'backend_unavailable','message':'Chưa kết nối được Default Player Backend.'}


EDUCATION_NAMES={'wewin_education_search','wewin_education_browse','wewin_education_playlists'}
MEDIA_NAMES.update(EDUCATION_NAMES)
for _name in sorted(EDUCATION_NAMES):
    MEDIA_DEFINITIONS.append({'name':_name,
        'description':'Browse official WeWIN Education metadata. Audio availability is independent; never claim robot playback from search results.',
        'inputSchema':schema({'query':{'type':'string','maxLength':160},'cursor':{'type':'string','maxLength':256}},[])})
