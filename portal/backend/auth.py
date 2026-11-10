"""HttpOnly sessions, CSRF, password hashing and explicit resource authorization."""
import hashlib
import secrets
import time
import re
from uuid import uuid4
from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from .db import connection, audit
from .integrations import settings

router = APIRouter(prefix='/api/portal')
COOKIE = 'wewin_education'
SESSION_TTL = 8*3600
attempts = {}


def same_origin(request):
    if request.url.hostname not in ('localhost','127.0.0.1','::1') or request.headers.get('origin') != f"{request.url.scheme}://{request.headers.get('host','')}":
        raise HTTPException(403, 'Thao tác yêu cầu Portal cục bộ cùng origin')


def hash_password(password):
    salt = secrets.token_hex(16)
    return salt + ':' + hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex()


def verify_password(password, hashed):
    try:
        salt, expected = hashed.split(':')
        return secrets.compare_digest(expected, hashlib.scrypt(password.encode(),salt=salt.encode(),n=16384,r=8,p=1).hex())
    except ValueError:
        return False


def session(request: Request):
    token = request.cookies.get(COOKIE,'')
    if len(token) != 43:
        raise HTTPException(401,'Cần đăng nhập')
    with connection() as db:
        row = db.execute('SELECT s.csrf,s.expires,s.user_id,u.role,u.display_name FROM sessions s JOIN users u ON u.id=s.user_id WHERE token_hash=? AND u.active=1',
                         (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
    if not row or row['expires'] < time.time():
        raise HTTPException(401,'Phiên đăng nhập đã hết hạn')
    return dict(row)


def mutation(request: Request, auth=Depends(session), x_wewin_csrf: str=Header(default='')):
    same_origin(request)
    if not secrets.compare_digest(auth['csrf'],x_wewin_csrf):
        raise HTTPException(403,'CSRF không hợp lệ')
    return auth


def staff(auth=Depends(mutation)):
    if auth['role'] not in ('admin','teacher'):
        raise HTTPException(403,'Chỉ giáo viên hoặc quản trị được thay đổi nội dung')
    return auth


def administrator(auth=Depends(mutation)):
    if auth['role'] != 'admin':
        raise HTTPException(403,'Cần quyền quản trị')
    return auth


def can_view_student(auth, student_id):
    if auth['role']=='admin' or auth['user_id']==student_id:
        return
    if auth['role']=='guardian':
        with connection() as db:
            if db.execute('SELECT 1 FROM guardian_links WHERE guardian_id=? AND student_id=?',(auth['user_id'],student_id)).fetchone():
                return
    if auth['role']=='teacher':
        with connection() as db:
            if db.execute('SELECT 1 FROM teacher_students WHERE teacher_id=? AND student_id=?',(auth['user_id'],student_id)).fetchone():
                return
    raise HTTPException(403,'Không có quyền truy cập hồ sơ học tập này')


def check_owner(auth, owner):
    if auth['role']!='admin' and auth['user_id']!=owner:
        raise HTTPException(403,'Không có quyền với tài nguyên này')


def require_robot(robot_id, auth):
    from .integrations import source_robots
    robot = next((r for r in source_robots() if r['id']==robot_id),None)
    if not robot:
        raise HTTPException(404,'Không tìm thấy Robot trong WeWIN hoặc legacy registry')
    if auth['role']!='admin':
        with connection() as db:
            if not db.execute('SELECT 1 FROM device_bindings WHERE device_id=? AND user_id=?',(robot_id,auth['user_id'])).fetchone():
                raise HTTPException(403,'Robot chưa được gán cho tài khoản này')
    return robot


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    username: str = Field(min_length=1,max_length=80)
    password: str = Field(min_length=1,max_length=256)


def make_session(response, request, user_id, role):
    token, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
    with connection() as db:
        db.execute('DELETE FROM sessions WHERE expires<?',(int(time.time()),))
        db.execute('INSERT INTO sessions VALUES(?,?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),csrf,int(time.time())+SESSION_TTL,role,user_id))
        audit(db,'login',user_id)
    response.set_cookie(COOKIE,token,max_age=SESSION_TTL,httponly=True,samesite='strict',secure=request.url.scheme=='https')
    return {'role':role,'user_id':user_id,'csrf':csrf}


def throttle(request):
    key = request.client.host if request.client else 'local'
    now = time.time()
    for host in list(attempts):
        attempts[host]=[t for t in attempts[host] if now-t<300]
        if not attempts[host]:
            del attempts[host]
    attempts.setdefault(key,[])
    if len(attempts[key])>=15:
        raise HTTPException(429,'Quá nhiều lần đăng nhập. Thử lại sau 5 phút')
    attempts[key].append(now)


@router.post('/login')
def token_login(request: Request,response: Response,authorization: str=Header(default='')):
    same_origin(request)
    throttle(request)
    scheme,_,provided=authorization.partition(' ')
    if scheme.lower()!='bearer' or not settings.ADMIN_SYNC_TOKEN or not secrets.compare_digest(provided,settings.ADMIN_SYNC_TOKEN):
        raise HTTPException(401,'Thông tin quản trị không hợp lệ')
    return make_session(response,request,'local-admin','admin')


@router.post('/auth/login')
def password_login(body: Credentials,request: Request,response: Response):
    same_origin(request)
    throttle(request)
    with connection() as db:
        user=db.execute('SELECT * FROM users WHERE username=? AND active=1',(body.username,)).fetchone()
    hashed=user['password_hash'] if user else '00000000000000000000000000000000:'+'0'*128
    if not verify_password(body.password,hashed) or not user:
        raise HTTPException(401,'Tên đăng nhập hoặc mật khẩu không hợp lệ')
    return make_session(response,request,user['id'],user['role'])


@router.get('/session')
def whoami(auth=Depends(session)):
    return auth


@router.post('/logout')
def logout(request: Request,response: Response,auth=Depends(mutation)):
    with connection() as db:
        db.execute('DELETE FROM sessions WHERE token_hash=?',(hashlib.sha256(request.cookies[COOKIE].encode()).hexdigest(),))
        audit(db,'logout',auth['user_id'])
    response.delete_cookie(COOKIE)
    return {'status':'signed_out'}


class UserInput(Credentials):
    display_name: str=Field(min_length=1,max_length=100)
    role: str=Field(pattern='^(admin|teacher|student|guardian)$')
    password: str=Field(min_length=12,max_length=256)


@router.get('/users')
def users(auth=Depends(session)):
    if auth['role']!='admin':
        raise HTTPException(403,'Cần quyền quản trị')
    with connection() as db:
        return {'items':[dict(r) for r in db.execute('SELECT id,username,display_name,role,active FROM users ORDER BY created_at')]}


@router.post('/users',status_code=201)
def create_user(body: UserInput,auth=Depends(administrator)):
    if not re.fullmatch(r'[a-zA-Z0-9_.-]{3,80}',body.username):
        raise HTTPException(422,'Tên đăng nhập cần 3–80 ký tự chữ, số, dấu chấm, gạch ngang')
    uid=uuid4().hex
    with connection() as db:
        if db.execute('SELECT 1 FROM users WHERE username=?',(body.username,)).fetchone():
            raise HTTPException(409,'Tên đăng nhập đã tồn tại')
        db.execute('INSERT INTO users VALUES(?,?,?,?,?,?,?)',(uid,body.username,body.display_name,hash_password(body.password),body.role,1,int(time.time())))
        db.execute('INSERT INTO user_profiles(user_id) VALUES(?)',(uid,))
        audit(db,'create_user',auth['user_id'],uid)
    return {'id':uid}


class Ownership(BaseModel):
    user_id: str
    device_id: str


@router.post('/device-bindings')
def assign_robot(body: Ownership,auth=Depends(administrator)):
    require_robot(body.device_id,auth)
    with connection() as db:
        if not db.execute('SELECT 1 FROM users WHERE id=? AND active=1',(body.user_id,)).fetchone():
            raise HTTPException(422,'Tài khoản không tồn tại')
        db.execute('INSERT OR IGNORE INTO devices VALUES(?,?,?)',(body.device_id,'connector_registry',int(time.time())))
        db.execute('INSERT OR IGNORE INTO device_bindings VALUES(?,?)',(body.device_id,body.user_id))
        audit(db,'assign_robot',auth['user_id'],body.device_id)
    return {'status':'assigned_locally'}


class GuardianLink(BaseModel):
    guardian_id: str
    student_id: str


@router.post('/guardian-links')
def guardian_link(body: GuardianLink,auth=Depends(administrator)):
    with connection() as db:
        for uid,role in [(body.guardian_id,'guardian'),(body.student_id,'student')]:
            if not db.execute('SELECT 1 FROM users WHERE id=? AND role=? AND active=1',(uid,role)).fetchone():
                raise HTTPException(422,'Liên kết yêu cầu tài khoản người giám hộ và học sinh hợp lệ')
        db.execute('INSERT OR IGNORE INTO guardian_links VALUES(?,?)',(body.guardian_id,body.student_id))
        audit(db,'link_guardian',auth['user_id'],body.student_id)
    return {'status':'linked'}


class ProfileInput(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    display_name: str=Field(min_length=1,max_length=100)
    level: str=Field(pattern='^(STARTER|A1|A2|B1|B2|C1|C2)$')
    goal: str=Field(default='',max_length=500)


@router.get('/profile')
def profile(auth=Depends(session)):
    with connection() as db:
        row=db.execute('SELECT p.level,p.goal,u.display_name FROM user_profiles p JOIN users u ON u.id=p.user_id WHERE p.user_id=?',(auth['user_id'],)).fetchone()
    return dict(row) if row else {'level':'STARTER','goal':'','display_name':auth['display_name']}


@router.put('/profile')
def update_profile(body: ProfileInput,auth=Depends(mutation)):
    with connection() as db:
        db.execute('UPDATE users SET display_name=? WHERE id=?',(body.display_name,auth['user_id']))
        db.execute('INSERT INTO user_profiles VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET level=excluded.level,goal=excluded.goal',(auth['user_id'],body.level,body.goal))
        audit(db,'update_profile',auth['user_id'])
    return {'status':'saved','level_evidence':'self_selected_not_assessed'}
