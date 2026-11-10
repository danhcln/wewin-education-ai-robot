"""Explicit teacher, role and knowledge associations; admin grants educational scope."""
import time
import sqlite3
from contextlib import closing
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from .db import connection, audit
from . import db as storage
from .auth import session, mutation, administrator, staff, check_owner, can_view_student, require_robot

router=APIRouter(prefix='/api/portal')

def migrate_relationships():
    with connection() as db:
        if db.execute('SELECT 1 FROM schema_version WHERE version=3').fetchone():
            return
        with closing(sqlite3.connect(storage.DB.parent / f'education-before-v3-{uuid4().hex}.sqlite3')) as out:
            db.backup(out)
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE teacher_students(teacher_id TEXT NOT NULL REFERENCES users(id), student_id TEXT NOT NULL REFERENCES users(id), PRIMARY KEY(teacher_id,student_id))')
        db.execute('CREATE TABLE user_role_bindings(user_id TEXT PRIMARY KEY REFERENCES users(id), role_id TEXT NOT NULL REFERENCES ai_roles(id), updated_at INTEGER NOT NULL)')
        db.execute('CREATE TABLE knowledge_bindings(id INTEGER PRIMARY KEY AUTOINCREMENT, document_id TEXT NOT NULL REFERENCES knowledge_documents(id) ON DELETE CASCADE, role_id TEXT REFERENCES ai_roles(id), device_id TEXT REFERENCES devices(id), owner_id TEXT NOT NULL REFERENCES users(id), created_at INTEGER NOT NULL, CHECK(role_id IS NOT NULL OR device_id IS NOT NULL))')
        db.execute('INSERT INTO schema_version VALUES(3,?)',(int(time.time()),))

class TeacherStudent(BaseModel):
    teacher_id: str
    student_id: str

@router.post('/teacher-students')
def assign_teacher(body: TeacherStudent,auth=Depends(administrator)):
    with connection() as db:
        for uid,role in [(body.teacher_id,'teacher'),(body.student_id,'student')]:
            if not db.execute('SELECT 1 FROM users WHERE id=? AND role=? AND active=1',(uid,role)).fetchone():
                raise HTTPException(422,'Cần giáo viên và học sinh hợp lệ')
        db.execute('INSERT OR IGNORE INTO teacher_students VALUES(?,?)',(body.teacher_id,body.student_id))
        audit(db,'assign_teacher',auth['user_id'],body.student_id)
    return {'status':'assigned'}

@router.get('/students')
def students(auth=Depends(session)):
    with connection() as db:
        if auth['role']=='admin':
            rows=db.execute("SELECT id,display_name FROM users WHERE role='student' AND active=1").fetchall()
        elif auth['role'] in ('teacher','guardian'):
            table,column=('teacher_students','teacher_id') if auth['role']=='teacher' else ('guardian_links','guardian_id')
            rows=db.execute(f'SELECT u.id,u.display_name FROM users u JOIN {table} t ON t.student_id=u.id WHERE t.{column}=? AND u.active=1',(auth['user_id'],)).fetchall()
        else:
            rows=[]
    return {'items':[dict(r) for r in rows]}

class RoleBinding(BaseModel):
    role_id: str
    user_id: str|None=None

@router.post('/role-bindings')
def role_binding(body: RoleBinding,auth=Depends(mutation)):
    uid=body.user_id or auth['user_id']
    if uid!=auth['user_id']:
        can_view_student(auth,uid)
    with connection() as db:
        if not db.execute('SELECT 1 FROM users WHERE id=? AND active=1',(uid,)).fetchone():
            raise HTTPException(422,'Hồ sơ người dùng không tồn tại')
        row=db.execute('SELECT * FROM ai_roles WHERE id=?',(body.role_id,)).fetchone()
        if not row or row['status']!='active':
            raise HTTPException(422,'Chọn vai trò Active')
        db.execute('INSERT INTO user_role_bindings VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET role_id=excluded.role_id,updated_at=excluded.updated_at',(uid,body.role_id,int(time.time())))
        audit(db,'assign_user_role',auth['user_id'],uid)
    return {'status':'saved_backend_only','message':'Đã gán vai trò trong Portal; chưa áp dụng Cloud/robot'}

class KnowledgeBinding(BaseModel):
    role_id: str|None=None
    device_id: str|None=None

@router.post('/knowledge/{kid}/bindings')
def knowledge_binding(kid: str,body: KnowledgeBinding,auth=Depends(staff)):
    if not body.role_id and not body.device_id:
        raise HTTPException(422,'Cần chọn vai trò hoặc robot')
    with connection() as db:
        row=db.execute('SELECT * FROM knowledge_documents WHERE id=?',(kid,)).fetchone()
        if not row:
            raise HTTPException(404,'Không tìm thấy tài liệu')
        check_owner(auth,row['owner_id'])
        if body.role_id:
            role=db.execute('SELECT * FROM ai_roles WHERE id=?',(body.role_id,)).fetchone()
            if not role:
                raise HTTPException(422,'Không tìm thấy vai trò')
            check_owner(auth,role['owner_id'])
        if body.device_id:
            require_robot(body.device_id,auth)
            db.execute('INSERT OR IGNORE INTO devices VALUES(?,?,?)',(body.device_id,'connector_registry',int(time.time())))
        db.execute('INSERT INTO knowledge_bindings(document_id,role_id,device_id,owner_id,created_at) VALUES(?,?,?,?,?)',(kid,body.role_id,body.device_id,auth['user_id'],int(time.time())))
        audit(db,'bind_knowledge',auth['user_id'],kid)
    return {'status':'bound_locally','message':'Liên kết tại Portal; chưa kích hoạt truy xuất trên Cloud Agent'}

@router.get('/knowledge/{kid}/bindings')
def knowledge_bindings(kid: str,auth=Depends(session)):
    with connection() as db:
        row=db.execute('SELECT owner_id FROM knowledge_documents WHERE id=?',(kid,)).fetchone()
        if not row:
            raise HTTPException(404,'Không tìm thấy tài liệu')
        check_owner(auth,row['owner_id'])
        return {'items':[dict(r) for r in db.execute('SELECT role_id,device_id,created_at FROM knowledge_bindings WHERE document_id=?',(kid,))]}
