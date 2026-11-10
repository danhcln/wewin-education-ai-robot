"""Versioned WeWIN AI role library. Publishing a role never changes Cloud."""
import json
import time
from uuid import uuid4
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field
from .auth import session,staff,check_owner
from .db import connection,audit
from .cloud_config import limit_action

router=APIRouter(prefix='/api/portal')


class Role(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    title: str=Field(min_length=1,max_length=120)
    avatar: str=Field(default='teacher',max_length=20)
    description: str=Field(default='',max_length=2000)
    system_prompt: str=Field(min_length=1,max_length=12000)
    greeting: str=Field(default='Win nghe đây ạ!',max_length=300)
    voice_preference: str=Field(default='',max_length=120)
    language: str=Field(default='vi-VN',max_length=32)
    audience: str=Field(default='Học sinh',max_length=120)
    skills: list[str]=Field(default_factory=list,max_length=30)
    status: str=Field(default='draft',pattern='^(draft|active|archived)$')
    lesson_id: str=Field(default='',max_length=120)
    knowledge_pack: str=Field(default='',max_length=120)
    learning_path: str=Field(default='',max_length=120)
    media_pack: str=Field(default='',max_length=120)
    version: int=Field(default=1,ge=1)


def role_payload(row):
    data=json.loads(row['payload'])
    if row['id'].startswith('builtin-') and row['version']==1 and row['created_at']==row['updated_at'] and data.get('avatar') in ('W','teacher',None):
        slug=row['id'].removeprefix('builtin-')
        data['avatar']={'english-teacher':'teacher','storytelling':'story'}.get(slug,slug)
    model=Role(**{**data,'version':row['version']})
    return model.model_dump()


def readable_role(db,rid,auth):
    row=db.execute('SELECT * FROM ai_roles WHERE id=?',(rid,)).fetchone()
    if not row:
        raise HTTPException(404,'Không tìm thấy vai trò')
    if row['status']!='active':
        check_owner(auth,row['owner_id'])
    return row


def present(row,auth):
    result={**dict(row),**role_payload(row)};result.pop('payload',None)
    result['can_edit']=auth['role']=='admin' or (auth['role']=='teacher' and row['owner_id']==auth['user_id'])
    result['can_view_prompt']=auth['role'] in ('admin','teacher')
    if not result['can_view_prompt']:
        result.pop('system_prompt',None)
    result['display_name']=result['title'] if result['title'].startswith('WeWIN') or not row['id'].startswith('builtin-') else 'WeWIN '+result['title']
    if row['id']=='builtin-consultant' and result['title']=='WeWIN Consultant':
        result['display_name']='WeWIN Education Consultant'
    return result


@router.get('/roles')
def list_roles(auth=Depends(session)):
    with connection() as db:
        rows=db.execute("SELECT * FROM ai_roles WHERE status='active' OR owner_id=? OR ?='admin' ORDER BY title",(auth['user_id'],auth['role'])).fetchall()
    return {'items':[present(row,auth) for row in rows]}


@router.get('/roles/{rid}')
def get_role(rid: str,auth=Depends(session)):
    with connection() as db:
        return present(readable_role(db,rid,auth),auth)


def validate_role_bindings(db,body,auth):
    from .robots import validate_references
    validate_references(db,body.model_dump(),auth)


@router.post('/roles',status_code=201)
def create_role(body: Role,auth=Depends(staff)):
    limit_action(auth,'role_write',30)
    if body.version!=1:
        raise HTTPException(422,'Vai trò mới bắt đầu ở phiên bản 1')
    rid=uuid4().hex;now=int(time.time())
    with connection() as db:
        validate_role_bindings(db,body,auth)
        db.execute('INSERT INTO ai_roles(id,owner_id,title,payload,status,created_at,updated_at,version) VALUES(?,?,?,?,?,?,?,?)',(rid,auth['user_id'],body.title,body.model_dump_json(),body.status,now,now,1))
        db.execute('INSERT INTO role_versions VALUES(?,?,?,?,?)',(rid,1,body.model_dump_json(),now,auth['user_id']))
        audit(db,'create_role',auth['user_id'],rid,1)
    return {'id':rid,'version':1,'status':body.status}


@router.put('/roles/{rid}')
def update_role(rid: str,body: Role,auth=Depends(staff)):
    limit_action(auth,'role_write',30)
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row=readable_role(db,rid,auth);check_owner(auth,row['owner_id'])
        if row['version']!=body.version:
            raise HTTPException(409,'Vai trò đã thay đổi. Tải phiên bản mới trước khi lưu.')
        validate_role_bindings(db,body,auth)
        updated=body.model_copy(update={'version':body.version+1});now=int(time.time())
        db.execute('UPDATE ai_roles SET title=?,payload=?,status=?,updated_at=?,version=? WHERE id=?',(updated.title,updated.model_dump_json(),updated.status,now,updated.version,rid))
        db.execute('INSERT INTO role_versions VALUES(?,?,?,?,?)',(rid,updated.version,updated.model_dump_json(),now,auth['user_id']))
        audit(db,'update_role',auth['user_id'],rid,updated.version)
    return {'id':rid,'version':updated.version,'status':updated.status}


@router.get('/roles/{rid}/history')
def role_history(rid: str,auth=Depends(session)):
    if auth['role'] not in ('admin','teacher'):
        raise HTTPException(403,'Không có quyền xem lịch sử prompt')
    with connection() as db:
        row=readable_role(db,rid,auth);check_owner(auth,row['owner_id'])
        rows=db.execute('SELECT version,payload,updated_at,actor FROM role_versions WHERE role_id=? ORDER BY version DESC LIMIT 100',(rid,)).fetchall()
    return {'items':[dict(r,payload=json.loads(r['payload'])) for r in rows]}
