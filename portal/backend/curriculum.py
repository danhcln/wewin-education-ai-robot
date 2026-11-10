"""Published curricula with ordered modules, enrollment and scored completion rules."""
from contextlib import closing
import sqlite3
import time
import json
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException
from pydantic import Field
from . import db as storage
from .db import connection, audit
from .auth import session, mutation, staff, check_owner
from .learning import Strict, readable_lesson

router=APIRouter(prefix='/api/portal')


def migrate_curriculum():
    with connection() as db:
        if db.execute('SELECT 1 FROM schema_version WHERE version=4').fetchone():
            return
        with closing(sqlite3.connect(storage.DB.parent/f'education-before-v4-{uuid4().hex}.sqlite3')) as out:
            db.backup(out)
        db.execute('BEGIN IMMEDIATE')
        db.execute('ALTER TABLE learning_paths ADD COLUMN minimum_score REAL NOT NULL DEFAULT 0 CHECK(minimum_score BETWEEN 0 AND 100)')
        db.execute("CREATE TABLE curricula(id TEXT PRIMARY KEY,owner_id TEXT NOT NULL REFERENCES users(id),title TEXT NOT NULL,description TEXT NOT NULL,level TEXT NOT NULL,minimum_score REAL NOT NULL CHECK(minimum_score BETWEEN 0 AND 100),status TEXT NOT NULL CHECK(status IN ('draft','published','archived')),created_at INTEGER NOT NULL,updated_at INTEGER NOT NULL)")
        db.execute('CREATE TABLE curriculum_modules(id TEXT PRIMARY KEY,curriculum_id TEXT NOT NULL REFERENCES curricula(id) ON DELETE CASCADE,title TEXT NOT NULL,position INTEGER NOT NULL,UNIQUE(curriculum_id,position))')
        db.execute('CREATE TABLE curriculum_lessons(module_id TEXT NOT NULL REFERENCES curriculum_modules(id) ON DELETE CASCADE,lesson_id TEXT NOT NULL REFERENCES lessons(id),position INTEGER NOT NULL,PRIMARY KEY(module_id,lesson_id),UNIQUE(module_id,position))')
        db.execute('CREATE TABLE curriculum_enrollments(user_id TEXT NOT NULL REFERENCES users(id),curriculum_id TEXT NOT NULL REFERENCES curricula(id),path_id TEXT NOT NULL REFERENCES learning_paths(id),created_at INTEGER NOT NULL,PRIMARY KEY(user_id,curriculum_id))')
        db.execute('CREATE TABLE path_modules(id TEXT PRIMARY KEY,path_id TEXT NOT NULL REFERENCES learning_paths(id) ON DELETE CASCADE,title TEXT NOT NULL,position INTEGER NOT NULL,UNIQUE(path_id,position))')
        db.execute('CREATE TABLE path_module_lessons(module_id TEXT NOT NULL REFERENCES path_modules(id) ON DELETE CASCADE,lesson_id TEXT NOT NULL REFERENCES lessons(id),position INTEGER NOT NULL,PRIMARY KEY(module_id,lesson_id))')
        db.execute('CREATE INDEX curriculum_status_idx ON curricula(status,level)')
        db.execute('INSERT INTO schema_version VALUES(4,?)',(int(time.time()),))


class Module(Strict):
    title: str=Field(min_length=1,max_length=180)
    lesson_ids: list[str]=Field(min_length=1,max_length=100)


class Curriculum(Strict):
    title: str=Field(min_length=1,max_length=180)
    description: str=Field(default='',max_length=2000)
    level: str=Field(default='STARTER',pattern='^(STARTER|A1|A2|B1|B2|C1|C2)$')
    minimum_score: float=Field(default=0,ge=0,le=100)
    status: str=Field(default='draft',pattern='^(draft|published|archived)$')
    modules: list[Module]=Field(min_length=1,max_length=30)


def modules_for(db,cid):
    return [dict(r,lesson_ids=[x[0] for x in db.execute('SELECT lesson_id FROM curriculum_lessons WHERE module_id=? ORDER BY position',(r['id'],))])
            for r in db.execute('SELECT id,title,position FROM curriculum_modules WHERE curriculum_id=? ORDER BY position',(cid,))]


def validate_modules(db,body,auth):
    import json
    ids=[lid for module in body.modules for lid in module.lesson_ids]
    if len(ids)!=len(set(ids)) or len(ids)>200:
        raise HTTPException(422,'Mỗi bài chỉ thuộc một module; tối đa 200 bài trong giáo trình')
    for lid in ids:
        lesson=readable_lesson(db,lid,auth)
        if lesson['status']!='published':
            raise HTTPException(422,'Giáo trình chỉ dùng bài đã xuất bản')
        if body.minimum_score>0 and not json.loads(lesson['payload']).get('exercises'):
            raise HTTPException(422,'Quy tắc điểm tối thiểu yêu cầu mọi bài có câu hỏi chấm điểm')


def write_modules(db,cid,body):
    db.execute('DELETE FROM curriculum_modules WHERE curriculum_id=?',(cid,))
    for i,module in enumerate(body.modules):
        mid=uuid4().hex
        db.execute('INSERT INTO curriculum_modules VALUES(?,?,?,?)',(mid,cid,module.title,i))
        db.executemany('INSERT INTO curriculum_lessons VALUES(?,?,?)',[(mid,lid,n) for n,lid in enumerate(module.lesson_ids)])


@router.get('/curricula')
def curricula(auth=Depends(session)):
    with connection() as db:
        rows=db.execute("SELECT * FROM curricula WHERE status='published' OR owner_id=? OR ?='admin' ORDER BY updated_at DESC",(auth['user_id'],auth['role'])).fetchall()
        return {'items':[dict(r,modules=modules_for(db,r['id'])) for r in rows]}


@router.post('/curricula',status_code=201)
def create_curriculum(body: Curriculum,auth=Depends(staff)):
    cid=uuid4().hex;now=int(time.time())
    with connection() as db:
        validate_modules(db,body,auth)
        db.execute('INSERT INTO curricula VALUES(?,?,?,?,?,?,?,?,?)',(cid,auth['user_id'],body.title,body.description,body.level,body.minimum_score,body.status,now,now))
        write_modules(db,cid,body)
        audit(db,'create_curriculum',auth['user_id'],cid)
    return {'id':cid,'status':body.status}


@router.put('/curricula/{cid}')
def update_curriculum(cid: str,body: Curriculum,auth=Depends(staff)):
    with connection() as db:
        row=db.execute('SELECT * FROM curricula WHERE id=?',(cid,)).fetchone()
        if not row:
            raise HTTPException(404,'Không tìm thấy giáo trình')
        check_owner(auth,row['owner_id'])
        validate_modules(db,body,auth)
        db.execute('UPDATE curricula SET title=?,description=?,level=?,minimum_score=?,status=?,updated_at=? WHERE id=?',(body.title,body.description,body.level,body.minimum_score,body.status,int(time.time()),cid))
        write_modules(db,cid,body)
        audit(db,'update_curriculum',auth['user_id'],cid)
    return {'id':cid,'status':body.status,'note':'Lộ trình đã ghi danh giữ snapshot cũ; cập nhật giáo trình không sửa tiến độ người học'}


@router.post('/curricula/{cid}/enroll')
def enroll_curriculum(cid: str,auth=Depends(mutation)):
    uid=auth['user_id'];now=int(time.time())
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute("SELECT * FROM curricula WHERE id=? AND status='published'",(cid,)).fetchone()
        if not row:
            raise HTTPException(404,'Giáo trình chưa được xuất bản hoặc không tồn tại')
        prior=db.execute('SELECT path_id FROM curriculum_enrollments WHERE user_id=? AND curriculum_id=?',(uid,cid)).fetchone()
        if prior:
            return {'path_id':prior[0],'status':'already_enrolled'}
        modules=modules_for(db,cid)
        # Check dependencies again: a lesson might have been archived after publication.
        for module in modules:
            for lid in module['lesson_ids']:
                lesson=readable_lesson(db,lid,auth)
                if lesson['status']!='published':
                    raise HTTPException(409,'Một bài đã ngừng xuất bản. Giáo viên cần cập nhật giáo trình trước khi ghi danh.')
                if row['minimum_score']>0 and not json.loads(lesson['payload']).get('exercises'):
                    raise HTTPException(409,'Một bài không còn câu hỏi chấm điểm. Giáo viên cần cập nhật giáo trình trước khi ghi danh.')
        pid=uuid4().hex
        db.execute('INSERT INTO learning_paths(id,owner_id,title,level,created_at,updated_at,minimum_score) VALUES(?,?,?,?,?,?,?)',(pid,uid,row['title'],row['level'],now,now,row['minimum_score']))
        position=0
        for n,module in enumerate(modules):
            mid=uuid4().hex
            db.execute('INSERT INTO path_modules VALUES(?,?,?,?)',(mid,pid,module['title'],n))
            for i,lid in enumerate(module['lesson_ids']):
                db.execute('INSERT INTO path_lessons VALUES(?,?,?)',(pid,lid,position));position+=1
                db.execute('INSERT INTO path_module_lessons VALUES(?,?,?)',(mid,lid,i))
        db.execute('INSERT INTO enrollments VALUES(?,?,?)',(uid,pid,now))
        db.execute('INSERT INTO curriculum_enrollments VALUES(?,?,?,?)',(uid,cid,pid,now))
        audit(db,'enroll_curriculum',uid,cid)
    return {'path_id':pid,'status':'enrolled','note':'Lộ trình là snapshot giáo trình tại thời điểm ghi danh'}
