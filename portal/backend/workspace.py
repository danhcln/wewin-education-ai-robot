"""Private tasks/memories, FTS knowledge, media references and provider workflows."""
from datetime import date
import re
import time
from urllib.parse import urlsplit
from uuid import uuid4
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import Field, field_validator
from .auth import session, mutation, staff, check_owner, require_robot, can_view_student
from .db import connection, audit
from .learning import Strict, readable_lesson
from .integrations import public_knowledge, approved_media
from . import providers
from .documents import extract

router=APIRouter(prefix='/api/portal')

def row_or_404(db,table,rid):
    row=db.execute(f'SELECT * FROM {table} WHERE id=?',(rid,)).fetchone()
    if not row:
        raise HTTPException(404,'Không tìm thấy tài nguyên')
    return row

class Task(Strict):
    title: str=Field(min_length=1,max_length=180)
    content: str=Field(default='',max_length=6000)
    due_date: date|None=None
    priority: str=Field(default='normal',pattern='^(low|normal|high)$')
    status: str=Field(default='open',pattern='^(open|completed)$')
    student_id: str|None=None
    device_id: str|None=None
    lesson_id: str|None=None

def task_access(auth,row):
    if auth['role']!='admin' and auth['user_id'] not in (row['owner_id'],row['student_id']):
        raise HTTPException(403,'Không có quyền với nhiệm vụ này')

def task_refs(db,body,auth):
    if body.device_id:
        require_robot(body.device_id,auth)
        db.execute('INSERT OR IGNORE INTO devices VALUES(?,?,?)',(body.device_id,'connector_registry',int(time.time())))
    if body.student_id:
        if body.student_id!=auth['user_id']:
            if auth['role'] not in ('admin','teacher'):
                raise HTTPException(403,'Cần giáo viên được phân công hoặc quản trị để giao nhiệm vụ')
            can_view_student(auth,body.student_id)
        if not db.execute('SELECT 1 FROM users WHERE id=? AND active=1',(body.student_id,)).fetchone():
            raise HTTPException(422,'Không tìm thấy người học')
    if body.lesson_id:
        readable_lesson(db,body.lesson_id,auth)

@router.get('/tasks')
def tasks(q: str=Query(default='',max_length=200),auth=Depends(session)):
    with connection() as db:
        rows=db.execute("SELECT * FROM tasks WHERE (owner_id=? OR student_id=? OR ?='admin') AND title LIKE ? ORDER BY status,COALESCE(due_date,'9999'),updated_at DESC LIMIT 200",(auth['user_id'],auth['user_id'],auth['role'],'%'+q+'%')).fetchall()
    return {'items':[dict(r) for r in rows]}

@router.post('/tasks',status_code=201)
def create_task(body: Task,auth=Depends(mutation)):
    tid=uuid4().hex;now=int(time.time())
    with connection() as db:
        task_refs(db,body,auth)
        db.execute('INSERT INTO tasks VALUES(?,?,?,?,?,?,?,?,?,?,?,?)',(tid,auth['user_id'],body.title,body.content,body.due_date.isoformat() if body.due_date else None,body.priority,body.status,body.student_id,body.device_id,body.lesson_id,now,now))
        db.execute('INSERT INTO task_history(task_id,actor,action,at) VALUES(?,?,?,?)',(tid,auth['user_id'],'created',now))
        audit(db,'create_task',auth['user_id'],tid)
    return {'id':tid}

@router.put('/tasks/{tid}')
def update_task(tid: str,body: Task,auth=Depends(mutation)):
    with connection() as db:
        row=row_or_404(db,'tasks',tid);check_owner(auth,row['owner_id']);task_refs(db,body,auth)
        db.execute('UPDATE tasks SET title=?,content=?,due_date=?,priority=?,status=?,student_id=?,device_id=?,lesson_id=?,updated_at=? WHERE id=?',(body.title,body.content,body.due_date.isoformat() if body.due_date else None,body.priority,body.status,body.student_id,body.device_id,body.lesson_id,int(time.time()),tid))
        db.execute('INSERT INTO task_history(task_id,actor,action,at) VALUES(?,?,?,?)',(tid,auth['user_id'],'updated',int(time.time())))
        audit(db,'update_task',auth['user_id'],tid)
    return {'id':tid}

@router.post('/tasks/{tid}/complete')
def complete_task(tid: str,auth=Depends(mutation)):
    with connection() as db:
        row=row_or_404(db,'tasks',tid);task_access(auth,row)
        db.execute("UPDATE tasks SET status='completed',updated_at=? WHERE id=?",(int(time.time()),tid))
        db.execute('INSERT INTO task_history(task_id,actor,action,at) VALUES(?,?,?,?)',(tid,auth['user_id'],'completed',int(time.time())))
        audit(db,'complete_task',auth['user_id'],tid)
    return {'status':'completed'}

@router.get('/tasks/{tid}/history')
def task_history(tid: str,auth=Depends(session)):
    with connection() as db:
        task_access(auth,row_or_404(db,'tasks',tid))
        return {'items':[dict(r) for r in db.execute('SELECT action,at FROM task_history WHERE task_id=? ORDER BY id DESC',(tid,))]}

@router.delete('/tasks/{tid}')
def delete_task(tid: str,auth=Depends(mutation)):
    with connection() as db:
        row=row_or_404(db,'tasks',tid);check_owner(auth,row['owner_id'])
        db.execute('DELETE FROM tasks WHERE id=?',(tid,))
        db.execute('INSERT INTO task_history(task_id,actor,action,at) VALUES(?,?,?,?)',(tid,auth['user_id'],'deleted',int(time.time())))
        audit(db,'delete_task',auth['user_id'],tid)
    return {'status':'deleted'}

class Memory(Strict):
    title: str=Field(min_length=1,max_length=180)
    content: str=Field(min_length=1,max_length=6000)
    category: str=Field(default='learning_goal',pattern='^(vocabulary|level|preference|unfinished|mistake|learning_goal)$')
    device_id: str|None=None
    session_id: str|None=None
    consent: bool

    @field_validator('title','content')
    @classmethod
    def no_secrets(cls,value):
        if re.search(r'(?i)(password|mật khẩu|token|api[_ -]?key|secret)\s*[:=]|sk-[a-zA-Z0-9]{15,}|bearer\s+[a-zA-Z0-9_-]{20,}',value):
            raise ValueError('Không lưu mật khẩu, token hoặc API key vào bộ nhớ')
        return value

@router.get('/memories')
def memories(q: str=Query(default='',max_length=200),auth=Depends(session)):
    with connection() as db:
        return {'items':[dict(r) for r in db.execute('SELECT * FROM memories WHERE owner_id=? AND (title LIKE ? OR content LIKE ?) ORDER BY updated_at DESC LIMIT 200',(auth['user_id'],'%'+q+'%','%'+q+'%'))]}

def memory_refs(db,body,auth):
    if not body.consent:
        raise HTTPException(422,'Cần xác nhận lưu bộ nhớ lâu dài')
    if body.device_id:
        require_robot(body.device_id,auth)
        db.execute('INSERT OR IGNORE INTO devices VALUES(?,?,?)',(body.device_id,'connector_registry',int(time.time())))
    if body.session_id:
        row=row_or_404(db,'learning_sessions',body.session_id)
        if row['user_id']!=auth['user_id']:
            raise HTTPException(403,'Buổi học không thuộc tài khoản này')

@router.post('/memories',status_code=201)
def create_memory(body: Memory,auth=Depends(mutation)):
    mid=uuid4().hex;now=int(time.time())
    with connection() as db:
        memory_refs(db,body,auth)
        db.execute('INSERT INTO memories VALUES(?,?,?,?,?,?,?,?,?)',(mid,auth['user_id'],body.title,body.content,body.category,body.device_id,body.session_id,now,now))
        audit(db,'create_memory',auth['user_id'],mid)
    return {'id':mid}

@router.put('/memories/{mid}')
def update_memory(mid: str,body: Memory,auth=Depends(mutation)):
    with connection() as db:
        row=row_or_404(db,'memories',mid)
        if row['owner_id']!=auth['user_id']:
            raise HTTPException(403,'Bộ nhớ riêng tư thuộc tài khoản khác')
        memory_refs(db,body,auth)
        db.execute('UPDATE memories SET title=?,content=?,category=?,device_id=?,session_id=?,updated_at=? WHERE id=?',(body.title,body.content,body.category,body.device_id,body.session_id,int(time.time()),mid))
        audit(db,'update_memory',auth['user_id'],mid)
    return {'id':mid}

@router.delete('/memories/{mid}')
def delete_memory(mid: str,auth=Depends(mutation)):
    with connection() as db:
        row=row_or_404(db,'memories',mid)
        if row['owner_id']!=auth['user_id']:
            raise HTTPException(403,'Bộ nhớ riêng tư thuộc tài khoản khác')
        db.execute('DELETE FROM memories WHERE id=?',(mid,));audit(db,'delete_memory',auth['user_id'],mid)
    return {'status':'deleted'}

class Document(Strict):
    title: str=Field(min_length=1,max_length=180)
    content: str=Field(min_length=1,max_length=200000)

@router.get('/knowledge')
def knowledge(q: str=Query(default='',max_length=200),auth=Depends(session)):
    with connection() as db:
        if q.strip():
            terms=re.findall(r'\w+',q)[:20]
            match=' AND '.join('"'+term+'"' for term in terms)
            rows=db.execute("SELECT d.* FROM knowledge_documents d JOIN knowledge_fts f ON f.id=d.id WHERE knowledge_fts MATCH ? AND (d.owner_id=? OR ?='admin') LIMIT 50",(match or '""',auth['user_id'],auth['role'])).fetchall()
        else:
            rows=db.execute("SELECT * FROM knowledge_documents WHERE owner_id=? OR ?='admin' ORDER BY updated_at DESC LIMIT 50",(auth['user_id'],auth['role'])).fetchall()
    return {'items':[dict(r,source='portal') for r in rows], 'connector_items':public_knowledge(q), 'index':'SQLite FTS5 (Portal); Connector public policy (read only)'}

@router.post('/knowledge',status_code=201)
def create_document(body: Document,auth=Depends(staff)):
    kid=uuid4().hex;now=int(time.time())
    with connection() as db:
        db.execute('INSERT INTO knowledge_documents VALUES(?,?,?,?,?,?,?)',(kid,auth['user_id'],body.title,body.content,'indexed',now,now))
        audit(db,'create_knowledge',auth['user_id'],kid)
    return {'id':kid,'status':'indexed'}

@router.post('/knowledge/upload',status_code=201)
def upload_document(file: UploadFile=File(...),auth=Depends(staff)):
    data=file.file.read(3*1024*1024+1)
    if len(data)>3*1024*1024:
        raise HTTPException(413,'Tài liệu tối đa 3 MB')
    content=extract(data,file.filename or '')
    return create_document(Document(title=(file.filename or 'Tài liệu')[:180],content=content),auth)

@router.post('/knowledge/{kid}/reindex')
def reindex(kid: str,auth=Depends(staff)):
    with connection() as db:
        row=row_or_404(db,'knowledge_documents',kid);check_owner(auth,row['owner_id'])
        db.execute('UPDATE knowledge_documents SET updated_at=? WHERE id=?',(int(time.time()),kid))
        audit(db,'reindex_knowledge',auth['user_id'],kid)
    return {'status':'indexed'}

@router.delete('/knowledge/{kid}')
def delete_document(kid: str,auth=Depends(staff)):
    with connection() as db:
        row=row_or_404(db,'knowledge_documents',kid);check_owner(auth,row['owner_id'])
        db.execute('DELETE FROM knowledge_documents WHERE id=?',(kid,));audit(db,'delete_knowledge',auth['user_id'],kid)
    return {'status':'deleted'}

class Media(Strict):
    title: str=Field(min_length=1,max_length=180)
    kind: str=Field(pattern='^(video_reference|audio_asset)$')
    url: str=Field(max_length=2000)

    @field_validator('url')
    @classmethod
    def safe_url(cls,value):
        p=urlsplit(value)
        if p.scheme!='https' or not p.hostname or p.username or p.password:
            raise ValueError('Dùng URL HTTPS không chứa thông tin đăng nhập')
        return value

@router.get('/media')
def media(auth=Depends(session)):
    with connection() as db:
        rows=db.execute("SELECT * FROM media_assets WHERE owner_id=? OR ?='admin' ORDER BY created_at DESC",(auth['user_id'],auth['role'])).fetchall()
    return {'items':[dict(r,status='reference_only') for r in rows],'connector_items':approved_media() if auth['role']=='admin' else [],
            'robot_streaming':'unsupported','bluetooth':'unsupported',
            'note':'Catalog audio đã duyệt của Connector chỉ đọc và chỉ quản trị xem được. Điều khiển player/streaming cần adapter riêng.'}

@router.get('/media/connector/{asset_id}/audio')
def connector_audio(asset_id: str,auth=Depends(session)):
    if auth['role']!='admin':
        raise HTTPException(403,'Cần quản trị để nghe audio Connector chưa được gán quyền trong Portal')
    from fastapi.responses import FileResponse
    from src.media.asset_service import get_assets
    from src.media.youtube import MediaError
    try:
        record,path=get_assets().get(asset_id)
    except MediaError:
        raise HTTPException(404,'Audio gốc không khả dụng hoặc chưa được duyệt') from None
    return FileResponse(path,media_type='audio/ogg')

@router.post('/media',status_code=201)
def create_media(body: Media,auth=Depends(staff)):
    mid=uuid4().hex
    with connection() as db:
        db.execute('INSERT INTO media_assets VALUES(?,?,?,?,?,?)',(mid,auth['user_id'],body.title,body.kind,body.url,int(time.time())))
        audit(db,'create_media',auth['user_id'],mid)
    return {'id':mid,'status':'reference_only'}

class MediaBinding(Strict):
    lesson_id: str

@router.post('/media/{mid}/bind')
def bind_media(mid: str,body: MediaBinding,auth=Depends(staff)):
    with connection() as db:
        check_owner(auth,row_or_404(db,'media_assets',mid)['owner_id'])
        check_owner(auth,readable_lesson(db,body.lesson_id,auth)['owner_id'])
        db.execute('INSERT OR IGNORE INTO media_lesson_bindings VALUES(?,?)',(mid,body.lesson_id))
        audit(db,'bind_media',auth['user_id'],mid)
    return {'status':'bound_locally'}

@router.get('/providers')
def provider_status(auth=Depends(session)):
    return providers.capabilities()

@router.post('/ocr')
def image_ocr(file: UploadFile=File(...),auth=Depends(mutation)):
    data=file.file.read(providers.MAX_IMAGE+1)
    text=providers.ocr(data,file.content_type)
    return {'text':text,'provider':'tesseract','status':'review_required','image_retained':False}

class Homework(Strict):
    question: str=Field(min_length=1,max_length=12000)
    consent: bool

@router.post('/homework',status_code=201)
def solve_homework(body: Homework,auth=Depends(mutation)):
    if not body.consent:
        raise HTTPException(422,'Cần đồng ý gửi câu hỏi đến AI provider đã cấu hình')
    hid=uuid4().hex
    try:
        explanation=providers.solve(body.question)
    except HTTPException:
        with connection() as db:
            db.execute('INSERT INTO homework_requests VALUES(?,?,?,?,?,?)',(hid,auth['user_id'],body.question,None,'provider_unavailable',int(time.time())))
            audit(db,'homework_provider_unavailable',auth['user_id'],hid)
        raise
    with connection() as db:
        db.execute('INSERT INTO homework_requests VALUES(?,?,?,?,?,?)',(hid,auth['user_id'],body.question,explanation,'review_required',int(time.time())))
        audit(db,'solve_homework',auth['user_id'],hid)
    return {'id':hid,'explanation':explanation,'status':'review_required'}

@router.get('/homework')
def homework_history(auth=Depends(session)):
    with connection() as db:
        return {'items':[dict(r) for r in db.execute('SELECT * FROM homework_requests WHERE owner_id=? ORDER BY created_at DESC LIMIT 50',(auth['user_id'],))]}

@router.get('/logs')
def logs(auth=Depends(session)):
    if auth['role']!='admin':
        raise HTTPException(403,'Nhật ký hệ thống yêu cầu quyền quản trị')
    with connection() as db:
        return {'items':[dict(r) for r in db.execute('SELECT action,robot_id,version,at,actor FROM audit ORDER BY id DESC LIMIT 200')]}
