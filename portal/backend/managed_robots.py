"""First-party inventory in the EXISTING Portal, never writes Connector data."""
import json
import sqlite3
import time
from contextlib import closing
from uuid import uuid4
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict,Field,field_validator
from .db import connection,audit
from .auth import session,administrator,require_robot

router=APIRouter(prefix='/api/portal')
TENANT='wewin-local'


def migrate_managed():
    from . import db as storage
    with connection() as db:
        if db.execute('SELECT 1 FROM schema_version WHERE version=7').fetchone():return
        with closing(sqlite3.connect(storage.DB.parent/f'education-before-v7-{uuid4().hex}.sqlite3')) as backup:db.backup(backup)
        db.execute('BEGIN IMMEDIATE')
        # A WeWIN Agent may deliberately serve several devices. Preserve every
        # v6 link while removing the old one-Agent-per-robot UNIQUE assumption.
        db.execute('CREATE TABLE self_hosted_links_v7(robot_id TEXT PRIMARY KEY REFERENCES devices(id),agent_id TEXT NOT NULL,version INTEGER NOT NULL,enabled INTEGER NOT NULL,created_by TEXT NOT NULL,updated_at INTEGER NOT NULL)')
        db.execute('INSERT INTO self_hosted_links_v7 SELECT * FROM self_hosted_links')
        assert db.execute('SELECT COUNT(*) FROM self_hosted_links_v7').fetchone()[0]==db.execute('SELECT COUNT(*) FROM self_hosted_links').fetchone()[0]
        db.execute('DROP TABLE self_hosted_links')
        db.execute('ALTER TABLE self_hosted_links_v7 RENAME TO self_hosted_links')
        db.execute('CREATE TABLE managed_robots(id TEXT PRIMARY KEY REFERENCES devices(id),name TEXT NOT NULL,device_id TEXT NOT NULL UNIQUE COLLATE NOCASE,client_id TEXT NOT NULL UNIQUE,kind TEXT NOT NULL,owner_id TEXT NOT NULL REFERENCES users(id),tenant_id TEXT NOT NULL,ownership_evidence TEXT NOT NULL,created_at INTEGER NOT NULL)')
        db.execute('CREATE TABLE managed_robot_observations(robot_id TEXT PRIMARY KEY REFERENCES managed_robots(id),observed_at INTEGER NOT NULL,payload TEXT NOT NULL)')
        db.execute('INSERT INTO schema_version VALUES(7,?)',(int(time.time()),))


def inventory():
    try:
        with connection() as db:rows=db.execute('SELECT r.*,o.observed_at,o.payload FROM managed_robots r LEFT JOIN managed_robot_observations o ON o.robot_id=r.id').fetchall()
    except sqlite3.OperationalError:return []  # Older migration fixtures remain usable.
    now=int(time.time());result=[]
    for row in rows:
        observed=json.loads(row['payload']) if row['payload'] else {}
        fresh=bool(row['observed_at'] and 0<=now-row['observed_at']<=20)
        result.append({'id':row['id'],'device_id':row['device_id'],'uuid':row['client_id'],'name':row['name'],'site_id':row['tenant_id'],'source':'wewin_managed','kind':row['kind'],'firmware':observed.get('device_version'),'online':bool(fresh and observed.get('online')),'last_seen':row['observed_at']*1000 if row['observed_at'] else None,'cloud_state':None,'evidence_source':'authenticated_wewin_gateway_snapshot' if fresh else 'wewin_registration_only','wifi_ip':None,'battery':None,'bluetooth_state':None})
    return result


def record(rid):
    try:
        with connection() as db:row=db.execute('SELECT * FROM managed_robots WHERE id=?',(rid,)).fetchone()
    except sqlite3.OperationalError:return None
    return dict(row) if row else None


def scoped_adapter(rid):
    from .self_hosted import SelfHostedAdapter
    row=record(rid)
    if not row:raise HTTPException(404,'Not a WeWIN-managed robot')
    with connection() as db:link=db.execute('SELECT * FROM self_hosted_links WHERE robot_id=?',(rid,)).fetchone()
    if not link:raise HTTPException(409,'WeWIN Agent target is absent')
    return row,SelfHostedAdapter({**dict(link),'owner_id':row['owner_id'],'tenant_id':row['tenant_id'],'device_id':row['device_id']})


class AddRobot(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name:str=Field(min_length=1,max_length=120)
    device_id:str=Field(min_length=6,max_length=100,pattern=r'^[a-zA-Z0-9_:-]+$')
    client_id:str=Field(min_length=6,max_length=100,pattern=r'^[a-zA-Z0-9_-]+$')
    kind:str=Field(default='simulator',pattern='^(simulator|physical)$')
    ownership_evidence:str=Field(min_length=12,max_length=300)
    ownership_attested:bool=False
    confirmed:bool=False
    @field_validator('device_id')
    @classmethod
    def canonical_id(cls,value):return value.lower()


class ProvisionConfirmation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    confirmed:bool=False


class BindingChange(BaseModel):
    model_config=ConfigDict(extra='forbid')
    confirmed:bool=False
    expected_binding_version:int=Field(ge=1)
    agent_id:str=Field(default='',max_length=120,pattern=r'^[a-zA-Z0-9_-]*$')


@router.post('/managed-robots')
def add_robot(body:AddRobot,auth=Depends(administrator)):
    if not body.confirmed or not body.ownership_attested:raise HTTPException(422,'Cần xác nhận quyền quản lý và tạo đăng ký WeWIN; chưa thay thiết bị')
    rid='managed_'+uuid4().hex;now=int(time.time())
    try:
        with connection() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM managed_robots WHERE device_id=? COLLATE NOCASE OR client_id=?',(body.device_id,body.client_id)).fetchone():raise HTTPException(409,'Device-ID hoặc Client-ID đã có trong WeWIN')
            db.execute('INSERT INTO devices VALUES(?,?,?)',(rid,'wewin_managed',now))
            db.execute('INSERT INTO managed_robots VALUES(?,?,?,?,?,?,?,?,?)',(rid,body.name,body.device_id,body.client_id,body.kind,auth['user_id'],TENANT,body.ownership_evidence,now))
            db.execute('INSERT INTO device_bindings VALUES(?,?)',(rid,auth['user_id']))
            db.execute('INSERT INTO self_hosted_links VALUES(?,?,1,1,?,?)',(rid,'wewin_'+rid,auth['user_id'],now))
            audit(db,'wewin_robot_registration_reserved',auth['user_id'],rid)
    except sqlite3.IntegrityError:raise HTTPException(409,'Đăng ký trùng hoặc thay đổi đồng thời')
    return {'id':rid,'agent_id':'wewin_'+rid,'state':'reserved_pending_agent_apply','physical_verified':False,'message':'Đã tạo Robot trong WeWIN. Áp dụng cấu hình Agent trước khi cấp bootstrap. Không ghi firmware/NVS hoặc đổi endpoint.'}


@router.get('/robots/{rid}/device-gateway')
def status(rid:str,auth=Depends(session)):
    require_robot(rid,auth)
    if auth['role']!='admin':raise HTTPException(403,'Quản trị mới được xem quản lý credential/binding')
    row,adapter=scoped_adapter(rid);remote=None;failure=None;agents=[]
    try:
        remote=adapter.request('GET','/v1/devices/'+row['device_id']+'/diagnostics',allow_missing=True)
        agents=adapter.request('GET','/v1/agents')['items']
        if remote:
            with connection() as db:db.execute('INSERT INTO managed_robot_observations VALUES(?,?,?) ON CONFLICT(robot_id) DO UPDATE SET observed_at=excluded.observed_at,payload=excluded.payload',(rid,int(time.time()),json.dumps(remote)))
    except HTTPException as exc:
        failure=str(exc.detail)
        with connection() as db:db.execute('INSERT INTO managed_robot_observations VALUES(?,?,?) ON CONFLICT(robot_id) DO UPDATE SET observed_at=excluded.observed_at,payload=excluded.payload',(rid,int(time.time()),json.dumps({'online':False,'evidence':'gateway_unavailable'})))
    if remote and remote['agent_id']!=adapter.link['agent_id']:failure='Binding Gateway khác đích Apply trong Portal; cần đối soát trước Apply.'
    return {'registration':{k:v for k,v in row.items() if k!='ownership_evidence'},'device':remote,'agents':agents,'error':failure,'physical_enrollment_enabled':False,'physical_verified':False,'independent_platform':True}


@router.post('/robots/{rid}/device-gateway/provision')
def provision(rid:str,body:ProvisionConfirmation,auth=Depends(administrator)):
    require_robot(rid,auth);row,adapter=scoped_adapter(rid)
    if not body.confirmed:raise HTTPException(422,'Cần xác nhận cấp credential WeWIN')
    if row['kind']=='physical':raise HTTPException(403,'Robot thật đang khóa cutover. Phiên này chỉ cấp bootstrap cho simulator.')
    result=adapter.request('POST','/v1/device-provisions',{**{k:row[k] for k in ('device_id','client_id','kind','ownership_evidence')},'agent_id':adapter.link['agent_id'],'ownership_attested':True,'confirmed':True,'ttl_seconds':86400})
    with connection() as db:audit(db,'wewin_bootstrap_issued_once',auth['user_id'],rid)
    return result


@router.post('/robots/{rid}/device-gateway/revoke')
def revoke(rid:str,body:ProvisionConfirmation,auth=Depends(administrator)):
    require_robot(rid,auth);row,adapter=scoped_adapter(rid)
    if not body.confirmed:raise HTTPException(422,'Cần xác nhận revoke')
    result=adapter.request('POST','/v1/devices/'+row['device_id']+'/revoke',{'confirmed':True})
    with connection() as db:audit(db,'wewin_device_revoked',auth['user_id'],rid)
    return result


@router.post('/robots/{rid}/device-gateway/rotate')
def rotate(rid:str,body:BindingChange,auth=Depends(administrator)):
    require_robot(rid,auth);row,adapter=scoped_adapter(rid)
    if row['kind']=='physical':raise HTTPException(403,'Physical credential changes require separate cutover approval')
    result=adapter.request('POST','/v1/devices/'+row['device_id']+'/credentials/rotate',body.model_dump())
    with connection() as db:audit(db,'wewin_device_credential_rotated',auth['user_id'],rid)
    return result


@router.post('/robots/{rid}/device-gateway/binding')
def bind(rid:str,body:BindingChange,auth=Depends(administrator)):
    require_robot(rid,auth);row,adapter=scoped_adapter(rid)
    if row['kind']=='physical':raise HTTPException(403,'Physical Agent rebinding requires separate approval')
    if not body.confirmed or not body.agent_id:raise HTTPException(422,'Cần xác nhận Agent mới')
    expected=adapter.link['version']
    result=adapter.request('POST','/v1/devices/'+row['device_id']+'/binding',body.model_dump())
    observed=adapter.request('GET','/v1/devices/'+row['device_id']+'/diagnostics')
    if observed['agent_id']!=body.agent_id or observed['binding_version']!=result['binding_version']:raise HTTPException(502,'Binding readback mismatch; refresh before any retry')
    with connection() as db:
        changed=db.execute('UPDATE self_hosted_links SET agent_id=?,version=version+1,updated_at=? WHERE robot_id=? AND version=?',(body.agent_id,int(time.time()),rid,expected)).rowcount
        if not changed:raise HTTPException(409,'Server binding changed but Portal target changed concurrently. Refresh and reconcile; no automatic rollback.')
        audit(db,'wewin_device_binding_readback_verified',auth['user_id'],rid,result['binding_version'])
    return result
