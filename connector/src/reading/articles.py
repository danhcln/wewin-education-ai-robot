"""Public-cache reading, extractive summaries, and bounded capability sessions."""
from dataclasses import dataclass
import hashlib
import re
import secrets
import threading
import time
import unicodedata

from .public_web import PublicWebReader, ReadError


def text_value(value, name, maximum):
    if not isinstance(value, str) or not value.strip() or len(value)>maximum:
        raise ReadError('invalid_arguments', name+' không hợp lệ.')
    return value.strip()


def integer(value, name, low, high):
    if type(value) is not int or not low<=value<=high:
        raise ReadError('invalid_arguments',name+' ngoài giới hạn cho phép.')
    return value


def speech_text(content):
    if not isinstance(content,str) or not content.strip():
        raise ReadError('empty_content','Bài viết không có nội dung đọc.')
    if len(content)>100000:
        raise ReadError('too_large','Bài viết vượt 100.000 ký tự; chưa thể đọc toàn bộ.')
    return ' '.join(unicodedata.normalize('NFC',content).split())


def chunks(text, limit=600):
    """Preserve normalized text, prefer sentence then word boundaries, cap hard."""
    parts=[]
    while text:
        if len(text)<=limit:
            parts.append(text);break
        candidates=list(re.finditer(r'[.!?。！？](?:\s|$)',text[:limit]))
        end=candidates[-1].start()+1 if candidates and candidates[-1].start()>=limit//3 else text.rfind(' ',0,limit+1)
        if end<=0:end=limit
        parts.append(text[:end]);text=text[end:].lstrip()
    return parts


def summary(text):
    """Extract source sentences only; no model/provider, no invented assertions."""
    sentences=[s.strip() for s in re.split(r'(?<=[.!?。！？])\s+',text) if s.strip()]
    # A lead-sentence summary is intentionally deterministic and auditable.
    selected=[];size=0
    for s in sentences:
        if len(selected)==3:break
        if size+len(s)+(1 if selected else 0)>900:break
        selected.append(s);size+=len(s)+(1 if len(selected)>1 else 0)
    if selected:return ' '.join(selected)
    return chunks(text,600)[0]


@dataclass
class Session:
    url: str
    title: str
    digest: str
    parts: list
    external: bool
    expires: float
    created: float
    cursor: int = 1


class ArticleReader:
    def __init__(self, web=None, clock=time.monotonic, max_sessions=64, ttl=900, max_chars=1000000):
        self.web=web or PublicWebReader();self.clock=clock
        self.max_sessions,self.ttl,self.max_chars=max_sessions,ttl,max_chars
        self.sessions={};self.lock=threading.RLock()

    def _expire(self):
        for key,state in list(self.sessions.items()):
            if self.clock()>=state.expires or self.clock()-state.created>=3600:
                del self.sessions[key]

    @staticmethod
    def _token(value):
        if not isinstance(value,str) or not re.fullmatch(r'[A-Za-z0-9_-]{43}',value):
            raise ReadError('invalid_reading_id','Mã lượt đọc không hợp lệ; hãy bắt đầu lại bài viết.')
        return value

    def find(self, db, args):
        query=text_value(args.get('query'),'query',200)
        limit=integer(args.get('limit',3),'limit',1,5)
        found=db.search(query,limit)
        # FTS intentionally uses OR terms for general QA. Article selection needs
        # title matches ahead of pages that merely repeat "IELTS" in the body.
        def folded(value):
            value=unicodedata.normalize('NFKD',value.casefold().replace('đ','d'))
            return re.sub(r'[^a-z0-9]+',' ',''.join(c for c in value if not unicodedata.combining(c))).strip()
        generic={'bai','viet','chuong','trinh','cua','wewin','education','doc','tom','tat','ve'}
        tokens=[t for t in folded(query).split() if t not in generic] or folded(query).split()
        phrase=' '.join(tokens)
        with db.get_connection() as conn:
            rows=[dict(r) for r in conn.execute('SELECT title,url,category,substr(content,1,300) AS snippet FROM public_pages')]
        matches=[r for r in rows if tokens and set(tokens).issubset(set(folded(r['title']).split()))]
        matches.sort(key=lambda r:(folded(r['title'])==phrase,folded(r['title']).startswith(phrase),
                                   phrase in folded(r['title']),-len(r['title'])),reverse=True)
        combined=[];seen=set()
        for row in [*matches,*found]:
            if row['url'] not in seen:
                combined.append(row);seen.add(row['url'])
        found=combined[:limit]
        return {'status':'ok' if found else 'not_found','query':query,
                'articles':[{k:r[k] for k in ('title','url','category','snippet')} for r in found],
                'instruction':'Chọn đúng bài và URL trước khi đọc. Nếu mơ hồ, hỏi người dùng chọn bài.'}

    @staticmethod
    def _page(db,url):
        page=db.get_page(text_value(url,'url',2048))
        if not page:
            raise ReadError('not_found','Không tìm thấy bài viết công khai được duyệt trong cache WeWIN.')
        return page

    @staticmethod
    def _check_external_copy(db,text):
        # Do not let a public mirror/IP alias disclose a held cache article.
        # This reads policy inputs privately; no held title/URL/content is returned.
        with db.get_connection() as conn:
            held=conn.execute("SELECT content FROM pages WHERE id NOT IN (SELECT id FROM public_pages)").fetchall()
        for row in held:
            old=' '.join(unicodedata.normalize('NFC',row[0] or '').split())
            if old and (old==text or (min(len(old),len(text))>=60 and (old in text or text in old))):
                raise ReadError('publication_review','Nguồn trùng nội dung chưa được duyệt công khai; không đọc.')

    def start(self, db, args, external=False):
        mode=args.get('mode','read')
        if mode not in ('read','summary'):
            raise ReadError('invalid_arguments','mode chỉ nhận read hoặc summary.')
        limit=integer(args.get('chunk_chars',600),'chunk_chars',200,800)
        # Validate all arguments before external I/O.
        url=text_value(args.get('url'),'url',2048)
        if external:
            if args.get('user_requested') is not True:
                raise ReadError('explicit_request_required','Chỉ đọc URL ngoài khi người dùng yêu cầu rõ URL đó.')
            page=self.web.fetch(url)
        else:
            page=self._page(db,url)
        text=speech_text(page['content'])
        if external:self._check_external_copy(db,text)
        base={'status':'ok','mode':mode,'title':page['title'][:200],'source_url':page['url'],
              'source_kind':'external' if external else 'wewin_public_cache','untrusted_source_text':True,
              'audio_generated':False}
        if mode=='summary':
            return {**base,'text':summary(text),'summary_method':'extractive_lead_sentences',
                    'summary_scope':'Tối đa ba câu đầu phù hợp giới hạn; không phải tổng hợp đầy đủ bằng AI.',
                    'has_more':False}
        parts=chunks(text,limit)
        with self.lock:
            self._expire()
            if (len(self.sessions)>=self.max_sessions or
                    sum(sum(map(len,s.parts)) for s in self.sessions.values())+len(text)>self.max_chars):
                raise ReadError('session_capacity','Bộ nhớ lượt đọc đã đầy; dừng lượt cũ hoặc thử lại sau.')
            key=secrets.token_urlsafe(32)
            state=Session(page['url'],page['title'][:200],hashlib.sha256(text.encode()).hexdigest(),
                          parts,external,self.clock()+self.ttl,self.clock())
            self.sessions[key]=state
            return {**base,**self._part(key,state,1),'expires_in_seconds':self.ttl,
                    'instruction':'Chỉ đọc text của đoạn này. Chờ người dùng nói đọc tiếp; giữ reading_id và next_part trong hội thoại, không đọc mã thành tiếng.'}

    @staticmethod
    def _part(key,state,part):
        more=part<len(state.parts)
        return {'status':'ok','reading_id':key,'title':state.title,'source_url':state.url,
                'source_kind':'external' if state.external else 'wewin_public_cache',
                'untrusted_source_text':True,'audio_generated':False,'mode':'read',
                'part':part,'total_parts':len(state.parts),'text':state.parts[part-1],
                'has_more':more,'next_part':part+1 if more else None}

    def continue_reading(self,db,args):
        key=self._token(args.get('reading_id'))
        part=integer(args.get('part'),'part',1,1000)
        with self.lock:
            self._expire();state=self.sessions.get(key)
            if state is None:
                raise ReadError('reading_not_found','Lượt đọc đã dừng, hết hạn hoặc nằm ở process khác; hãy mở lại bài.')
            if not state.external:
                # Publication can be revoked or content edited between chunks.
                try:page=self._page(db,state.url)
                except ReadError:
                    del self.sessions[key]
                    raise
                text=speech_text(page['content'])
                if hashlib.sha256(text.encode()).hexdigest()!=state.digest or page['title'][:200]!=state.title:
                    del self.sessions[key]
                    raise ReadError('article_changed','Nội dung hoặc metadata đã đổi; mở lại bài để đọc bản hiện tại.')
            else:
                try:self._check_external_copy(db,' '.join(state.parts))
                except ReadError:
                    del self.sessions[key]
                    raise
            if part==state.cursor:
                # Repeated call for the last delivered part is safe after RPC retry.
                return self._part(key,state,part)
            if part!=state.cursor+1:
                raise ReadError('out_of_order','Số đoạn không khớp; dùng next_part của phản hồi gần nhất.')
            if part>len(state.parts):
                return {'status':'completed','has_more':False,'text':'Đã đọc hết bài viết.','audio_generated':False}
            state.cursor=part;state.expires=self.clock()+self.ttl
            return self._part(key,state,part)

    def stop(self,args):
        key=self._token(args.get('reading_id'))
        with self.lock:
            self._expire();self.sessions.pop(key,None)
        return {'status':'stopped','has_more':False,'audio_generated':False,
                'text':'Đã kết thúc lượt đọc trên backend.',
                'instruction':'Không yêu cầu thêm đoạn. Ngắt âm thanh đang phát phụ thuộc XiaoZhi và chưa được xác minh.'}


READING_TOOL_NAMES={'wewin_find_article','wewin_read_article','wewin_continue_reading',
                    'wewin_stop_reading','wewin_read_url'}
reader=ArticleReader()


def execute_reading_tool(name,args,db):
    try:
        if not isinstance(args,dict):raise ReadError('invalid_arguments','arguments phải là object.')
        if name=='wewin_find_article':return reader.find(db,args)
        if name=='wewin_read_article':return reader.start(db,args)
        if name=='wewin_read_url':return reader.start(db,args,external=True)
        if name=='wewin_continue_reading':return reader.continue_reading(db,args)
        if name=='wewin_stop_reading':return reader.stop(args)
        raise ReadError('unknown_tool','Không tìm thấy công cụ đọc.')
    except ReadError as e:
        result={'status':e.code,'message':e.message,'audio_generated':False}
        if name=='wewin_read_url' and isinstance(args,dict):
            from .public_web import validate_url
            try:result['source_url']=validate_url(args.get('url'))
            except ReadError:pass
        return result
