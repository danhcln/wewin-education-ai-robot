import json
import time
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from .db import connection, audit
from .auth import session, staff, require_robot, can_view_student
from .integrations import source_robots, read_status, TOOL_DEFINITIONS, RobotConfigurationAdapter
from .cloud_config import adapter_for,limit_action

router=APIRouter(prefix='/api/portal')


class Config(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version: int=Field(ge=0)
    assistant_name: str=Field(default='Win',min_length=1,max_length=80)
    robot_name: str=Field(default='Win',min_length=1,max_length=120)
    ai_role: str=Field(default='',max_length=120)
    persona: str=Field(default='Bạn là Win, trợ lý AI giáo dục của WeWIN Education. Bạn giao tiếp thân thiện, dễ hiểu, hỗ trợ học sinh học tiếng Anh và các môn học phù hợp, đồng thời có thể trả lời thông tin về WeWIN thông qua các công cụ được cấp quyền.',max_length=6000)
    system_prompt: str=Field(default='',max_length=12000)
    greeting: str=Field(default='Win nghe đây ạ!',max_length=300)
    language: str=Field(default='vi-VN',max_length=32)
    voice: str=Field(default='',max_length=120)
    voice_gender: str=Field(default='unspecified',pattern='^(unspecified|female|male|neutral)$')
    speech_rate: float=Field(default=1,ge=.5,le=2)
    speech_style: str=Field(default='Thân thiện, rõ ràng',max_length=120)
    ai_model: str=Field(default='',max_length=120)
    lesson_id: str=Field(default='',max_length=120)
    knowledge_pack: str=Field(default='',max_length=120)
    learning_path: str=Field(default='',max_length=120)
    media_pack: str=Field(default='',max_length=120)
    student_profile: str=Field(default='',max_length=120)
    role_version: int=Field(default=0,ge=0)


def authorized_robots(auth):
    robots=source_robots()
    if auth['role']=='admin':
        return robots
    with connection() as db:
        ids={r[0] for r in db.execute('SELECT device_id FROM device_bindings WHERE user_id=?',(auth['user_id'],))}
    return [r for r in robots if r['id'] in ids]


@router.get('/overview')
def overview(auth=Depends(session)):
    robots=authorized_robots(auth)
    with connection() as db:
        drafts=sum(bool(db.execute('SELECT 1 FROM robot_config WHERE robot_id=?',(r['id'],)).fetchone()) for r in robots)
    return {'robots':robots,'drafts':drafts,'mcp':read_status() if auth['role'] in ('admin','teacher') else 'restricted',
            'tools':len(TOOL_DEFINITIONS) if auth['role'] in ('admin','teacher') else 0,'source':'WeWIN inventory + Connector registry (legacy read only)',
            **RobotConfigurationAdapter.capabilities()}


@router.get('/robots/{robot_id}/config')
def get_config(robot_id: str,auth=Depends(session)):
    robot=require_robot(robot_id,auth)
    with connection() as db:
        row=db.execute('SELECT * FROM robot_config WHERE robot_id=?',(robot_id,)).fetchone()
        payload={**Config(version=0).model_dump(exclude={'version'}),**(json.loads(row['payload']) if row else {})}
        role=db.execute('SELECT title,version FROM ai_roles WHERE id=?',(payload['ai_role'],)).fetchone() if payload['ai_role'] else None
    if auth['role'] not in ('admin','teacher'):
        payload['system_prompt']=''
    return {'robot':robot,'version':row['version'] if row else 0,'config':payload,
            'prompt_redacted':auth['role'] not in ('admin','teacher'),
            'current_role':dict(role) if role else None,'provider_capabilities':adapter_for(robot_id).capabilities(),
            'sync_state':row['sync_state'] if row else 'draft','updated_at':row['updated_at'] if row else None,
            'wake_word':{'current':'Chưa xác minh từ thiết bị','target':'Hey, Win!','model':'Chưa có model Hey, Win đã xác minh',
                         'availability':'unverified','firmware_compatibility':'unverified','sensitivity':'unsupported','deployment':'unsupported','validation':'not_validated','apply_supported':False},
            'bluetooth':{'state':'Chưa có telemetry','scan_supported':False,'paired_devices':[]},
            'capabilities':RobotConfigurationAdapter.capabilities()}


def validate_references(db,payload,auth):
    for key,table in [('ai_role','ai_roles'),('lesson_id','lessons'),('knowledge_pack','knowledge_documents'),('learning_path','learning_paths'),('media_pack','media_assets')]:
        rid=payload.get(key)
        if not rid:
            continue
        row=db.execute(f'SELECT * FROM {table} WHERE id=?',(rid,)).fetchone()
        if not row:
            raise HTTPException(422,f'{key}: không tìm thấy nội dung')
        shared=(table=='lessons' and row['status']=='published') or (table=='ai_roles' and row['status']=='active')
        if auth['role']!='admin' and row['owner_id']!=auth['user_id'] and not shared:
            raise HTTPException(403,f'{key}: không có quyền truy cập')
    uid=payload.get('student_profile')
    if uid and not db.execute('SELECT 1 FROM users WHERE id=? AND active=1',(uid,)).fetchone():
        raise HTTPException(422,'Hồ sơ học sinh không tồn tại')
    if uid and uid!=auth['user_id']:
        can_view_student(auth,uid)


def persist_config(db,robot_id,payload,expected_version,auth,action='save_config'):
    """Caller owns BEGIN IMMEDIATE so config, bindings, history and audit commit together."""
    validate_references(db,payload,auth)
    current=db.execute('SELECT version FROM robot_config WHERE robot_id=?',(robot_id,)).fetchone()
    version=current[0] if current else 0
    if version!=expected_version:
        raise HTTPException(409,'Cấu hình đã thay đổi. Tải lại trước khi lưu')
    version+=1
    now=int(time.time())
    role=db.execute('SELECT version FROM ai_roles WHERE id=?',(payload['ai_role'],)).fetchone() if payload['ai_role'] else None
    if role and not payload.get('role_version'):
        payload['role_version']=role[0]
    if role and not db.execute('SELECT 1 FROM role_versions WHERE role_id=? AND version=?',(payload['ai_role'],payload['role_version'])).fetchone():
        raise HTTPException(422,'Phiên bản vai trò không tồn tại trong lịch sử')
    if not role:
        payload['role_version']=0
    blob=json.dumps(payload,ensure_ascii=False)
    db.execute('INSERT OR IGNORE INTO devices VALUES(?,?,?)',(robot_id,'connector_registry',now))
    db.execute('INSERT INTO config_history VALUES(?,?,?,?,?,?)',(robot_id,version,blob,'saved_backend_only',now,auth['user_id']))
    db.execute('INSERT INTO robot_config VALUES(?,?,?,?,?,?) ON CONFLICT(robot_id) DO UPDATE SET version=excluded.version,payload=excluded.payload,sync_state=excluded.sync_state,updated_at=excluded.updated_at,updated_by=excluded.updated_by',
               (robot_id,version,blob,'saved_backend_only',now,auth['user_id']))
    db.execute('INSERT INTO config_sync_history(robot_id,state,reason,at,actor) VALUES(?,?,?,?,?)',(robot_id,'saved_backend_only',action+': chưa có Cloud management adapter được xác minh',now,auth['user_id']))
    db.execute('DELETE FROM learning_bindings WHERE id=?',('robot-'+robot_id,))
    db.execute('INSERT INTO learning_bindings VALUES(?,?,?,?,?,?,?,?,?)',('robot-'+robot_id,payload['student_profile'] or auth['user_id'],robot_id,payload['ai_role'] or None,payload['lesson_id'] or None,payload['learning_path'] or None,payload['knowledge_pack'] or None,payload['media_pack'] or None,now))
    db.execute('DELETE FROM device_role_bindings WHERE robot_id=?',(robot_id,))
    if role:
        db.execute('INSERT INTO device_role_bindings VALUES(?,?,?,?,?)',(robot_id,payload['ai_role'],payload['role_version'],version,now))
    audit(db,action,auth['user_id'],robot_id,version)
    return {'version':version,'sync_state':'saved_backend_only','updated_at':now,'message':'Đã lưu vào WeWIN backend; chưa áp dụng lên robot hoặc Cloud'}


@router.put('/robots/{robot_id}/config')
def save_config(robot_id: str,body: Config,auth=Depends(staff)):
    require_robot(robot_id,auth)
    limit_action(auth,'config_save',60)
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        return persist_config(db,robot_id,body.model_dump(exclude={'version'}),body.version,auth)


@router.get('/robots/{robot_id}/history')
def history(robot_id: str,auth=Depends(session)):
    require_robot(robot_id,auth)
    with connection() as db:
        rows=db.execute('SELECT version,sync_state,updated_at,updated_by FROM config_history WHERE robot_id=? ORDER BY version DESC LIMIT 100',(robot_id,)).fetchall()
        sync=db.execute('SELECT state,reason,at FROM config_sync_history WHERE robot_id=? ORDER BY id DESC LIMIT 100',(robot_id,)).fetchall()
    return {'items':[dict(r) for r in rows],'sync':[dict(r) for r in sync],'device_events':[],
            'note':'Device, Bluetooth và audio events chưa có nguồn telemetry được xác minh'}


@router.get('/mcp')
def mcp(auth=Depends(session)):
    if auth['role'] not in ('admin','teacher'):
        raise HTTPException(403,'Cần quyền giáo viên hoặc quản trị')
    return {'bridge':read_status(),'tools':[{'name':t['name'],'description':t.get('description','')} for t in TOOL_DEFINITIONS],
            'last_successful_tool_call':None,'error_logs':[],**RobotConfigurationAdapter.capabilities(),
            'note':'Heartbeat bridge và danh sách tool khai báo trong Connector. Chưa có xác nhận tool được Cloud gọi thành công trong phiên này.'}
