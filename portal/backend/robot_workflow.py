"""Explicit candidate/confirmation/restore workflow. SAVE never implies Cloud APPLY."""
import json
import time
from uuid import uuid4
from urllib.parse import urlsplit
from fastapi import APIRouter,Depends,HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel,ConfigDict,Field,field_validator
from .auth import session,mutation,staff,administrator,require_robot
from .db import connection,audit,ROOT
from .robots import Config,authorized_robots,validate_references,persist_config
from .roles import readable_role,role_payload
from .cloud_config import adapter_for,limit_action
from .cloud_readiness import cloud_readiness

router=APIRouter(prefix='/api/portal')


@router.get('/cloud-connection-guide')
def connection_guide(auth=Depends(session)):
    if auth['role']!='admin':
        raise HTTPException(403,'Chỉ quản trị xem hướng dẫn cấp quyền tích hợp')
    return FileResponse(ROOT/'docs/ROBOT_AI_CLOUD_CONNECTION.md',media_type='text/plain; charset=utf-8')


@router.get('/robots')
def robots(auth=Depends(session)):
    return {'items':authorized_robots(auth)}


def desired(db,rid):
    row=db.execute('SELECT * FROM robot_config WHERE robot_id=?',(rid,)).fetchone()
    payload={**Config(version=0).model_dump(exclude={'version'}),**(json.loads(row['payload']) if row else {})}
    return payload,row['version'] if row else 0,row


def candidate(db,rid,payload,base,auth,role=None):
    previous,version,_=desired(db,rid)
    if base!=version:
        raise HTTPException(409,'Cấu hình đã thay đổi. Tải lại trước khi tạo candidate.')
    validate_references(db,payload,auth)
    now=int(time.time());cid=uuid4().hex
    db.execute('INSERT OR IGNORE INTO devices VALUES(?,?,?)',(rid,'connector_registry',now))
    db.execute('INSERT INTO config_candidates VALUES(?,?,?,?,?,?,?,?,?,0)',(cid,rid,base,json.dumps(payload,ensure_ascii=False),role['id'] if role else None,role['version'] if role else None,auth['user_id'],now,now+900))
    from .self_hosted import capture_target
    payload=capture_target(db,cid,adapter_for(rid),payload)
    db.execute('UPDATE config_candidates SET payload=? WHERE id=?',(json.dumps(payload,ensure_ascii=False),cid))
    audit(db,'create_config_candidate',auth['user_id'],rid,base)
    target=db.execute('SELECT agent_id,expected_revision,link_version FROM self_hosted_targets WHERE candidate_id=?',(cid,)).fetchone()
    from .self_hosted import PROFILE_FIELDS
    return {'id':cid,'base_version':base,'config':payload,'expires_at':now+900,'state':'draft','target':{**dict(target),'fields':list(PROFILE_FIELDS)} if target else None,
            'changes':[{'field':key,'before':previous.get(key),'after':value} for key,value in payload.items() if previous.get(key)!=value]}


@router.post('/robots/{rid}/config/candidates',status_code=201)
def configuration_candidate(rid: str,body: Config,auth=Depends(staff)):
    require_robot(rid,auth);limit_action(auth,'config_candidate',30)
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        result=candidate(db,rid,body.model_dump(exclude={'version'}),body.version,auth)
    result['capabilities']=adapter_for(rid).capabilities()
    return result


class RoleChoice(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version: int=Field(ge=0)
    role_version: int=Field(ge=1)


@router.post('/robots/{rid}/roles/{role_id}/candidate',status_code=201)
def role_candidate(rid: str,role_id: str,body: RoleChoice,auth=Depends(staff)):
    require_robot(rid,auth);limit_action(auth,'config_candidate',30)
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        role=readable_role(db,role_id,auth)
        if role['status']!='active':
            raise HTTPException(422,'Vai trò phải được Publish trước khi gán robot')
        if role['version']!=body.role_version:
            raise HTTPException(409,'Vai trò đã thay đổi; xem lại phiên bản mới trước khi chọn')
        data=role_payload(role);payload,_,_=desired(db,rid)
        payload.update(ai_role=role_id,role_version=role['version'],system_prompt=data['system_prompt'],greeting=data['greeting'],language=data['language'],persona=data['description'] or payload['persona'])
        if data['voice_preference']:
            payload['voice']=data['voice_preference']
        for key in ('lesson_id','knowledge_pack','learning_path','media_pack'):
            if data[key]:payload[key]=data[key]
        result=candidate(db,rid,Config(version=body.version,**payload).model_dump(exclude={'version'}),body.version,auth,role)
    result['capabilities']=adapter_for(rid).capabilities()
    return result


class Confirmation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    candidate_id: str=Field(min_length=1,max_length=64)
    confirmed: bool=False


def checked_candidate(db,rid,body,auth):
    if not body.confirmed:
        raise HTTPException(422,'Cần xác nhận nội dung candidate trước khi tiếp tục')
    row=db.execute('SELECT * FROM config_candidates WHERE id=? AND robot_id=?',(body.candidate_id,rid)).fetchone()
    if not row:
        raise HTTPException(404,'Không tìm thấy candidate của robot này')
    if row['created_by']!=auth['user_id']:
        raise HTTPException(403,'Candidate cần được xác nhận bởi tài khoản đã tạo')
    if row['consumed']:
        raise HTTPException(409,'Candidate đã được sử dụng. Tạo candidate mới cho thay đổi tiếp theo.')
    if row['expires_at']<=time.time():
        raise HTTPException(410,'Candidate đã hết hạn; kiểm tra và tạo lại')
    _,version,_=desired(db,rid)
    if version!=row['base_version']:
        raise HTTPException(409,'Cấu hình mới hơn đã được lưu; candidate cũ không được ghi đè')
    if row['role_id']:
        role=readable_role(db,row['role_id'],auth)
        if role['version']!=row['role_version'] or role['status']!='active':
            raise HTTPException(409,'Vai trò đã đổi phiên bản hoặc ngừng xuất bản; hãy xem lại')
    return row


def consume(db,rid,body,auth,expected_role=None):
    row=checked_candidate(db,rid,body,auth)
    if expected_role and row['role_id']!=expected_role:
        raise HTTPException(409,'Candidate không thuộc vai trò được chọn')
    result=persist_config(db,rid,json.loads(row['payload']),row['base_version'],auth,'role_bind_backend' if row['role_id'] else 'confirm_config_candidate')
    db.execute('UPDATE config_candidates SET consumed=1 WHERE id=?',(body.candidate_id,))
    return result


@router.post('/robots/{rid}/config/candidates/save')
def save_candidate(rid: str,body: Confirmation,auth=Depends(staff)):
    require_robot(rid,auth);limit_action(auth,'candidate_confirm',20)
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        return consume(db,rid,body,auth)


@router.post('/robots/{rid}/roles/{role_id}/apply')
def assign_role(rid: str,role_id: str,body: Confirmation,auth=Depends(mutation)):
    require_robot(rid,auth)
    if auth['role'] not in ('admin','teacher'):
        with connection() as db:audit(db,'role_apply_denied',auth['user_id'],rid)
        raise HTTPException(403,'Chỉ giáo viên/quản trị được gán vai trò cho Robot')
    limit_action(auth,'candidate_confirm',20)
    with connection() as db:audit(db,'role_apply_requested',auth['user_id'],rid)
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        result=consume(db,rid,body,auth,role_id)
        audit(db,'role_apply_backend_only',auth['user_id'],rid,result['version'])
    return {**result,'cloud_applied':False,'robot_applied':False,'message':'Đã gán vai trò trong WeWIN Backend. Chưa đồng bộ lên Robot hoặc Cloud.'}


@router.post('/robots/{rid}/config/apply')
def apply_cloud(rid: str,body: Confirmation,auth=Depends(mutation)):
    require_robot(rid,auth)
    if auth['role'] not in ('admin','teacher'):
        with connection() as db:audit(db,'cloud_apply_denied',auth['user_id'],rid)
        raise HTTPException(403,'Học sinh/người giám hộ không có quyền Apply Cloud')
    limit_action(auth,'cloud_apply',5)
    from .self_hosted import SelfHostedAdapter,apply_candidate
    adapter=adapter_for(rid)
    if isinstance(adapter,SelfHostedAdapter):
        with connection() as db:audit(db,'self_hosted_apply_requested',auth['user_id'],rid)
        return apply_candidate(rid,body,auth,adapter)
    with connection() as db:audit(db,'cloud_apply_requested',auth['user_id'],rid)
    # Even the disabled UI cannot bypass this server-side capability gate.
    with connection() as db:
        checked_candidate(db,rid,body,auth)
        audit(db,'cloud_apply_unsupported',auth['user_id'],rid)
        db.execute('INSERT INTO config_sync_history(robot_id,state,reason,at,actor) VALUES(?,?,?,?,?)',(rid,'unsupported','No authorized verified management adapter',int(time.time()),auth['user_id']))
    return adapter_for(rid).apply({})


@router.get('/robots/{rid}/config/sync-status')
def sync_status(rid: str,auth=Depends(session)):
    require_robot(rid,auth)
    with connection() as db:
        payload,version,row=desired(db,rid)
        observed=db.execute('SELECT * FROM config_observations WHERE robot_id=?',(rid,)).fetchone()
        events=db.execute('SELECT state,reason,at FROM config_sync_history WHERE robot_id=? ORDER BY id DESC LIMIT 30',(rid,)).fetchall()
    from .self_hosted import linked_adapter
    local=linked_adapter(rid)
    if local:
        capabilities=local.capabilities();remote=None;error=None
        if capabilities['read_supported']:
            try:remote=local.read()
            except HTTPException as exc:error=str(exc.detail)
        with connection() as db:job=db.execute('SELECT * FROM self_hosted_jobs WHERE robot_id=? ORDER BY updated_at DESC LIMIT 1',(rid,)).fetchone()
        observed=remote['config'].copy() if remote else None
        if observed and auth['role'] not in ('admin','teacher'):observed['system_prompt']=''
        state=row['sync_state'] if row else 'draft'
        server_matches=bool(remote and job and job['state']=='server_applied_verified' and remote['config_hash']==job['server_hash'] and remote['revision']==job['server_revision'] and job['config_version']==version)
        if job and job['state']=='server_applied_verified' and remote and not server_matches:state='out_of_sync'
        remote_state='server_applied_verified' if server_matches else 'unavailable' if not remote else 'out_of_sync' if job and job['state']=='server_applied_verified' else job['state'] if job else 'saved_backend_only'
        return {'state':state,'cloud_state':remote_state,'desired_version':version,'desired_updated_at':row['updated_at'] if row else None,'observed':observed,'observed_at':int(time.time()) if remote else None,'server_revision':remote['revision'] if remote else None,'server_applied':server_matches,'cloud_applied':False,'robot_applied':False,'capabilities':capabilities,'events':[dict(e) for e in events],'error':error}
    # External Cloud remains unsupported. Self-hosted server proof is separate.
    return {'state':row['sync_state'] if row else 'draft','cloud_state':'unsupported','desired_version':version,
            'desired_updated_at':row['updated_at'] if row else None,'observed':None,'observed_at':None,
            'historical_observation_available':bool(observed),'cloud_applied':False,'robot_applied':False,
            'capabilities':adapter_for(rid).capabilities(),'events':[dict(e) for e in events]}


@router.post('/robots/{rid}/config/read-cloud')
def read_cloud(rid: str,auth=Depends(staff)):
    require_robot(rid,auth);limit_action(auth,'cloud_read',10)
    from .self_hosted import SelfHostedAdapter
    adapter=adapter_for(rid)
    with connection() as db:audit(db,'self_hosted_read_requested' if isinstance(adapter,SelfHostedAdapter) else 'cloud_read_unsupported',auth['user_id'],rid)
    return adapter.read()


@router.get('/robots/{rid}/history/{version}')
def version_detail(rid: str,version: int,auth=Depends(session)):
    require_robot(rid,auth)
    if auth['role'] not in ('admin','teacher'):
        raise HTTPException(403,'Không có quyền xem lịch sử System Prompt')
    with connection() as db:
        row=db.execute('SELECT * FROM config_history WHERE robot_id=? AND version=?',(rid,version)).fetchone()
    if not row:raise HTTPException(404,'Không tìm thấy phiên bản cấu hình')
    return {**dict(row),'payload':json.loads(row['payload'])}


class Restore(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version: int=Field(ge=0)
    target_version: int=Field(ge=1)
    confirmed: bool=False


@router.post('/robots/{rid}/config/restore')
def restore(rid: str,body: Restore,auth=Depends(staff)):
    require_robot(rid,auth);limit_action(auth,'config_restore',10)
    if not body.confirmed:raise HTTPException(422,'Cần xác nhận khôi phục trong backend')
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row=db.execute('SELECT payload FROM config_history WHERE robot_id=? AND version=?',(rid,body.target_version)).fetchone()
        if not row:raise HTTPException(404,'Không tìm thấy phiên bản cần khôi phục')
        payload=Config(version=body.version,**json.loads(row['payload'])).model_dump(exclude={'version'})
        result=persist_config(db,rid,payload,body.version,auth,'restore_config_v'+str(body.target_version))
    return {**result,'restored_from':body.target_version}


class ConnectionProfile(BaseModel):
    model_config=ConfigDict(extra='forbid',str_strip_whitespace=True)
    version: int=Field(ge=0)
    provider: str=Field(min_length=1,max_length=100)
    agent_reference: str=Field(min_length=1,max_length=120,pattern=r'^[A-Za-z0-9_.:-]+$')
    origin: str=Field(max_length=400)
    documentation_url: str=Field(max_length=1000)
    credential_env: str=Field(pattern=r'^WEWIN_CLOUD_[A-Z0-9_]{1,80}$')

    @field_validator('origin','documentation_url')
    @classmethod
    def no_url_secrets(cls,value):
        p=urlsplit(value)
        if p.scheme!='https' or not p.hostname or p.username or p.password or p.query or p.fragment:
            raise ValueError('Cần URL HTTPS công khai, không chứa credential/query/fragment')
        return value.rstrip('/')

    @field_validator('origin')
    @classmethod
    def origin_only(cls,value):
        if urlsplit(value).path not in ('','/'):
            raise ValueError('Chỉ nhập origin của nhà cung cấp, không đoán API path')
        return value


@router.get('/robots/{rid}/cloud-connection')
def connection_profile(rid: str,auth=Depends(session)):
    require_robot(rid,auth)
    if auth['role']!='admin':raise HTTPException(403,'Chỉ quản trị xem thiết lập tích hợp')
    with connection() as db:
        row=db.execute('SELECT * FROM robot_cloud_links WHERE robot_id=?',(rid,)).fetchone()
    profile=dict(row) if row else None
    from .cloud_config import UnsupportedCloudAdapter
    capabilities=UnsupportedCloudAdapter(profile).capabilities()
    return {'profile':profile,'capabilities':capabilities,'readiness':cloud_readiness(rid,profile,capabilities),
            'next_steps':['Xác định Console thực sự điều khiển robot','Xin contract quản lý Agent và quyền đọc/sửa chính thức','Đặt credential trong biến môi trường server được chỉ định','Xác minh mapping, catalog, readback và concurrency trước khi mở Apply']}


@router.put('/robots/{rid}/cloud-connection')
def save_connection_profile(rid: str,body: ConnectionProfile,auth=Depends(administrator)):
    require_robot(rid,auth);limit_action(auth,'connection_profile',10)
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        old=db.execute('SELECT version FROM robot_cloud_links WHERE robot_id=?',(rid,)).fetchone()
        version=old[0] if old else 0
        if version!=body.version:raise HTTPException(409,'Thông tin kết nối đã thay đổi')
        db.execute('INSERT OR IGNORE INTO devices VALUES(?,?,?)',(rid,'connector_registry',int(time.time())))
        db.execute('INSERT INTO robot_cloud_links VALUES(?,?,?,?,?,?,?,?,?,?) ON CONFLICT(robot_id) DO UPDATE SET provider=excluded.provider,agent_reference=excluded.agent_reference,origin=excluded.origin,documentation_url=excluded.documentation_url,credential_env=excluded.credential_env,version=excluded.version,state=excluded.state,updated_at=excluded.updated_at,updated_by=excluded.updated_by',
                   (rid,body.provider,body.agent_reference,body.origin,body.documentation_url,body.credential_env,version+1,'verification_pending',int(time.time()),auth['user_id']))
        audit(db,'save_cloud_connection_request',auth['user_id'],rid,version+1)
    return {'version':version+1,'state':'verification_pending','message':'Đã lưu hồ sơ yêu cầu kết nối. Chưa xác minh API/Agent và chưa gửi yêu cầu ra Cloud.'}
