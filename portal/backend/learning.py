"""Lessons, roles, paths and real browser practice, scoped by authenticated identity."""
from datetime import datetime, timezone, timedelta
import json
import time
import unicodedata
from uuid import uuid4
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field
from .auth import session, mutation, staff, check_owner, can_view_student
from .db import connection, audit
from .roles import Role

router=APIRouter(prefix='/api/portal')


class Strict(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)


class Exercise(Strict):
    question: str=Field(min_length=1,max_length=1000)
    answer: str=Field(min_length=1,max_length=500)


class Lesson(Strict):
    title: str=Field(min_length=1,max_length=180)
    description: str=Field(default='',max_length=2000)
    level: str=Field(default='STARTER',pattern='^(STARTER|A1|A2|B1|B2|C1|C2)$')
    language: str=Field(default='en',max_length=32)
    topic: str=Field(default='General',max_length=120)
    content: str=Field(min_length=1,max_length=60000)
    vocabulary: list[str]=Field(default_factory=list,max_length=200)
    exercises: list[Exercise]=Field(default_factory=list,max_length=100)
    media_references: list[str]=Field(default_factory=list,max_length=30)
    status: str=Field(default='draft',pattern='^(draft|published|archived)$')


def row_content(row):
    result=dict(row)
    result.update(json.loads(result.pop('payload')))
    return result


def readable_lesson(db,lid,auth):
    row=db.execute('SELECT * FROM lessons WHERE id=?',(lid,)).fetchone()
    if not row:
        raise HTTPException(404,'Không tìm thấy bài học')
    if row['status']!='published':
        check_owner(auth,row['owner_id'])
    return row


@router.get('/lessons')
def lessons(q: str=Query(default='',max_length=200),level: str='',topic: str='',auth=Depends(session)):
    with connection() as db:
        rows=db.execute("SELECT * FROM lessons WHERE (status='published' OR owner_id=? OR ?='admin') AND (title LIKE ? OR topic LIKE ?) AND (?='' OR level=?) AND (?='' OR topic=?) ORDER BY updated_at DESC LIMIT 200",
                        (auth['user_id'],auth['role'],'%'+q+'%','%'+q+'%',level,level,topic,topic)).fetchall()
    return {'items':[row_content(r) for r in rows]}


@router.get('/lessons/{lid}')
def lesson_detail(lid: str,auth=Depends(session)):
    with connection() as db:
        result=row_content(readable_lesson(db,lid,auth))
        result['media_assets']=[dict(r) for r in db.execute('SELECT m.id,m.title,m.kind,m.url FROM media_assets m JOIN media_lesson_bindings b ON b.media_id=m.id WHERE b.lesson_id=?',(lid,))]
        return result


@router.post('/lessons',status_code=201)
def create_lesson(body: Lesson,auth=Depends(staff)):
    lid=uuid4().hex
    now=int(time.time())
    with connection() as db:
        db.execute('INSERT INTO lessons VALUES(?,?,?,?,?,?,?,?,?,?)',(lid,auth['user_id'],body.title,body.level,body.topic,body.language,body.model_dump_json(),body.status,now,now))
        audit(db,'create_lesson',auth['user_id'],lid)
    return {'id':lid,'status':body.status}


@router.put('/lessons/{lid}')
def update_lesson(lid: str,body: Lesson,auth=Depends(staff)):
    with connection() as db:
        row=readable_lesson(db,lid,auth)
        check_owner(auth,row['owner_id'])
        db.execute('UPDATE lessons SET title=?,level=?,topic=?,language=?,payload=?,status=?,updated_at=? WHERE id=?',(body.title,body.level,body.topic,body.language,body.model_dump_json(),body.status,int(time.time()),lid))
        audit(db,'update_lesson',auth['user_id'],lid)
    return {'id':lid,'status':body.status}


class PathInput(Strict):
    title: str=Field(min_length=1,max_length=180)
    level: str=Field(default='STARTER',max_length=32)
    lesson_ids: list[str]=Field(min_length=1,max_length=100)
    minimum_score: float=Field(default=0,ge=0,le=100)


@router.get('/paths')
def paths(auth=Depends(session)):
    with connection() as db:
        rows=db.execute('SELECT * FROM learning_paths WHERE owner_id=? OR ?=\'admin\' OR id IN (SELECT path_id FROM enrollments WHERE user_id=?)',(auth['user_id'],auth['role'],auth['user_id'])).fetchall()
        items=[]
        for r in rows:
            ids=[x[0] for x in db.execute('SELECT lesson_id FROM path_lessons WHERE path_id=? ORDER BY position',(r['id'],))]
            done={x[0] for x in db.execute('SELECT lesson_id FROM learning_progress WHERE user_id=? AND best_score>=?',(auth['user_id'],r['minimum_score']))}
            modules=[dict(m,lesson_ids=[x[0] for x in db.execute('SELECT lesson_id FROM path_module_lessons WHERE module_id=? ORDER BY position',(m['id'],))]) for m in db.execute('SELECT id,title,position FROM path_modules WHERE path_id=? ORDER BY position',(r['id'],))]
            items.append(dict(r,lesson_ids=ids,modules=modules,completed=sum(l in done for l in ids),next_lesson=next((l for l in ids if l not in done),None),completion_rule=f"Hoàn thành mọi bài; điểm tối thiểu {r['minimum_score']:g}/100"))
    return {'items':items}


def save_path(db,pid,body,auth):
    if len(set(body.lesson_ids))!=len(body.lesson_ids):
        raise HTTPException(422,'Một bài chỉ xuất hiện một lần trong lộ trình')
    for lid in body.lesson_ids:
        row=readable_lesson(db,lid,auth)
        if row['status']!='published':
            raise HTTPException(422,'Chỉ thêm bài đã xuất bản vào lộ trình')
        if body.minimum_score>0 and not json.loads(row['payload']).get('exercises'):
            raise HTTPException(422,'Điểm tối thiểu yêu cầu mọi bài có câu hỏi chấm điểm')
    db.execute('DELETE FROM path_lessons WHERE path_id=?',(pid,))
    db.executemany('INSERT INTO path_lessons VALUES(?,?,?)',[(pid,lid,i) for i,lid in enumerate(body.lesson_ids)])


@router.post('/paths',status_code=201)
def create_path(body: PathInput,auth=Depends(staff)):
    pid=uuid4().hex
    now=int(time.time())
    with connection() as db:
        db.execute('INSERT INTO learning_paths(id,owner_id,title,level,created_at,updated_at,minimum_score) VALUES(?,?,?,?,?,?,?)',(pid,auth['user_id'],body.title,body.level,now,now,body.minimum_score))
        save_path(db,pid,body,auth)
        audit(db,'create_path',auth['user_id'],pid)
    return {'id':pid}


@router.put('/paths/{pid}')
def update_path(pid: str,body: PathInput,auth=Depends(staff)):
    with connection() as db:
        row=db.execute('SELECT * FROM learning_paths WHERE id=?',(pid,)).fetchone()
        if not row:
            raise HTTPException(404,'Không tìm thấy lộ trình')
        check_owner(auth,row['owner_id'])
        if db.execute('SELECT 1 FROM curriculum_enrollments WHERE path_id=?',(pid,)).fetchone():
            raise HTTPException(409,'Lộ trình này là snapshot giáo trình; tạo lộ trình riêng để chỉnh sửa')
        save_path(db,pid,body,auth)
        db.execute('UPDATE learning_paths SET title=?,level=?,minimum_score=?,updated_at=? WHERE id=?',(body.title,body.level,body.minimum_score,int(time.time()),pid))
        audit(db,'update_path',auth['user_id'],pid)
    return {'id':pid}


class Enrollment(Strict):
    user_id: str


@router.post('/paths/{pid}/enroll')
def enroll(pid: str,body: Enrollment,auth=Depends(mutation)):
    if body.user_id!=auth['user_id']:
        if auth['role'] not in ('admin','teacher'):
            raise HTTPException(403,'Cần giáo viên được phân công hoặc quản trị')
        can_view_student(auth,body.user_id)
    with connection() as db:
        row=db.execute('SELECT * FROM learning_paths WHERE id=?',(pid,)).fetchone()
        if not row:
            raise HTTPException(404,'Không tìm thấy lộ trình')
        if auth['role']!='admin' and row['owner_id']!=auth['user_id'] and not db.execute('SELECT 1 FROM enrollments WHERE path_id=? AND user_id=?',(pid,auth['user_id'])).fetchone():
            raise HTTPException(403,'Lộ trình cần được quản trị ghi danh')
        if not db.execute('SELECT 1 FROM users WHERE id=? AND active=1',(body.user_id,)).fetchone():
            raise HTTPException(422,'Không tìm thấy người học')
        db.execute('INSERT OR IGNORE INTO enrollments VALUES(?,?,?)',(body.user_id,pid,int(time.time())))
        audit(db,'enroll',auth['user_id'],pid)
    return {'status':'enrolled'}


class Start(Strict):
    lesson_id: str


@router.post('/learning/sessions',status_code=201)
def start(body: Start,auth=Depends(mutation)):
    sid=uuid4().hex
    with connection() as db:
        row=readable_lesson(db,body.lesson_id,auth)
        if row['status']!='published':
            raise HTTPException(422,'Xuất bản bài học trước khi bắt đầu')
        # Reuse an unfinished attempt rather than generating inflated session counts.
        old=db.execute('SELECT id FROM learning_sessions WHERE user_id=? AND lesson_id=? AND completed_at IS NULL ORDER BY started_at DESC LIMIT 1',(auth['user_id'],body.lesson_id)).fetchone()
        if old:
            return {'id':old[0],'status':'in_progress'}
        db.execute('INSERT INTO learning_sessions(id,user_id,lesson_id,started_at,lesson_snapshot) VALUES(?,?,?,?,?)',(sid,auth['user_id'],body.lesson_id,int(time.time()),row['payload']))
        audit(db,'start_learning',auth['user_id'],sid)
    return {'id':sid,'status':'in_progress'}


class Finish(Strict):
    answers: list[str]=Field(default_factory=list,max_length=100)


def normalize(s):
    return ' '.join(unicodedata.normalize('NFKC',s).casefold().strip().split())


@router.post('/learning/sessions/{sid}/complete')
def finish(sid: str,body: Finish,auth=Depends(mutation)):
    now=int(time.time())
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT * FROM learning_sessions WHERE id=?',(sid,)).fetchone()
        if not row:
            raise HTTPException(404,'Không tìm thấy buổi học')
        if row['user_id']!=auth['user_id']:
            raise HTTPException(403,'Chỉ người học được hoàn thành buổi của mình')
        if row['completed_at']:
            raise HTTPException(409,'Buổi học đã hoàn thành')
        exercises=json.loads(row['lesson_snapshot']).get('exercises',[])
        if len(body.answers)!=len(exercises):
            raise HTTPException(422,'Cần trả lời đủ số câu hỏi')
        score=round(100*sum(normalize(a)==normalize(e['answer']) for a,e in zip(body.answers,exercises))/len(exercises),1) if exercises else None
        db.execute('UPDATE learning_sessions SET completed_at=?,duration_seconds=?,score=?,answers=? WHERE id=?',(now,max(0,now-row['started_at']),score,json.dumps(body.answers),sid))
        db.execute('INSERT INTO learning_progress VALUES(?,?,?,?) ON CONFLICT(user_id,lesson_id) DO UPDATE SET completed_at=excluded.completed_at,best_score=MAX(best_score,excluded.best_score)',(auth['user_id'],row['lesson_id'],now,score if score is not None else 0))
        audit(db,'complete_learning',auth['user_id'],sid)
    return {'status':'completed','score':score,'duration_seconds':max(0,now-row['started_at']),'evidence':'browser_practice','note':'Thời gian theo đồng hồ server giữa bắt đầu và nộp; không phải thời gian chú ý đã xác minh'}


@router.get('/learning/dashboard')
def dashboard(user_id: str='',auth=Depends(session)):
    uid=user_id or auth['user_id']
    can_view_student(auth,uid)
    with connection() as db:
        rows=[dict(r) for r in db.execute('SELECT s.id,s.lesson_id,l.title,s.started_at,s.completed_at,s.duration_seconds,s.score,s.evidence FROM learning_sessions s JOIN lessons l ON l.id=s.lesson_id WHERE s.user_id=? ORDER BY s.started_at DESC LIMIT 500',(uid,))]
        totals=db.execute('SELECT COUNT(*),COALESCE(SUM(duration_seconds),0),AVG(score) FROM learning_sessions WHERE user_id=? AND completed_at IS NOT NULL',(uid,)).fetchone()
        dates={datetime.fromtimestamp(r[0],timezone(timedelta(hours=7))).date() for r in db.execute('SELECT completed_at FROM learning_sessions WHERE user_id=? AND completed_at IS NOT NULL',(uid,))}
        today=datetime.now(timezone(timedelta(hours=7))).date()
        cursor=today if today in dates else today-timedelta(days=1)
        streak=0
        while cursor in dates:
            streak+=1;cursor-=timedelta(days=1)
        progress=db.execute('SELECT COUNT(*) FROM learning_progress WHERE user_id=?',(uid,)).fetchone()[0]
        recommendation=db.execute("SELECT id,title,level FROM lessons WHERE status='published' AND id NOT IN (SELECT lesson_id FROM learning_progress WHERE user_id=?) ORDER BY created_at LIMIT 1",(uid,)).fetchone()
        profile=db.execute('SELECT * FROM user_profiles WHERE user_id=?',(uid,)).fetchone()
        role=db.execute('SELECT r.id,r.title FROM user_role_bindings b JOIN ai_roles r ON r.id=b.role_id WHERE b.user_id=?',(uid,)).fetchone()
    return {'sessions':rows,'total_sessions':totals[0],'total_seconds':totals[1],'average_score':round(totals[2],1) if totals[2] is not None else None,'assigned_role':dict(role) if role else None,
            'streak':streak,'completed_lessons':progress,'recommended':dict(recommendation) if recommendation else None,'profile':dict(profile) if profile else None,
            'time_evidence':'elapsed_server_time_estimate','score_evidence':'exact_answer_matching','current':next((r for r in rows if not r['completed_at']),None)}


def seed_library():
    """Explicit starter content, never seeded student activity or robot telemetry."""
    definitions=[('english-teacher','WeWIN English Teacher','Giải thích tiếng Anh rõ ràng, đưa ví dụ phù hợp trình độ.'),
                 ('pronunciation','Pronunciation Coach','Hướng dẫn cách phát âm bằng mô tả; không tự nhận đã nghe âm thanh khi chưa có audio.'),
                 ('storytelling','Storytelling Assistant','Kể chuyện ngắn phù hợp lứa tuổi và hỏi câu hỏi đọc hiểu.'),
                 ('homework','Homework Tutor','Hướng dẫn giải từng bước, gợi ý để học sinh tự suy nghĩ.'),
                 ('buddy','Learning Buddy','Đồng hành học tập, khích lệ và đặt mục tiêu nhỏ.'),
                 ('stem','STEM Tutor','Giải thích toán, khoa học và tư duy logic bằng ví dụ.'),
                 ('consultant','WeWIN Consultant','Tra cứu nguồn WeWIN được cấp quyền trước khi trả lời thông tin trung tâm.'),
                 ('general','General Assistant','Hỗ trợ học tập thân thiện và nêu rõ giới hạn kiến thức.')]
    now=int(time.time())
    with connection() as db:
        for rid,title,prompt in definitions:
            role=Role(title=title,avatar={'english-teacher':'teacher','storytelling':'story'}.get(rid,rid),description=prompt,system_prompt='Bạn là Win, trợ lý giáo dục WeWIN. '+prompt,skills=['learning'],status='active')
            db.execute('INSERT OR IGNORE INTO ai_roles(id,owner_id,title,payload,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',('builtin-'+rid,'local-admin',title,role.model_dump_json(),'active',now,now))
        lesson=Lesson(title='Hello, Win! — Chào hỏi bằng tiếng Anh',description='Bài mẫu biên soạn sẵn để bắt đầu học trên web.',topic='Greetings',content='Hello! My name is Win. What is your name?\nHello = Xin chào. Goodbye = Tạm biệt. Thank you = Cảm ơn.\nHãy đọc các câu trên, sau đó trả lời câu hỏi để ôn tập.',vocabulary=['Hello — Xin chào','Goodbye — Tạm biệt','Thank you — Cảm ơn'],exercises=[Exercise(question='Viết từ tiếng Anh nghĩa là “Xin chào”.',answer='Hello'),Exercise(question='Viết từ tiếng Anh nghĩa là “Tạm biệt”.',answer='Goodbye')],status='published')
        db.execute('INSERT OR IGNORE INTO lessons VALUES(?,?,?,?,?,?,?,?,?,?)',('builtin-hello','local-admin',lesson.title,lesson.level,lesson.topic,lesson.language,lesson.model_dump_json(),'published',now,now))
