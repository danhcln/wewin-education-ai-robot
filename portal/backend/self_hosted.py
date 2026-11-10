"""Portal adapter for the independently operated WeWIN AI staging service."""
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit
from uuid import uuid4
import httpx
from fastapi import APIRouter,Depends,HTTPException
from pydantic import BaseModel,ConfigDict
from .db import ROOT,connection,audit
from .auth import session,administrator,require_robot

router=APIRouter(prefix='/api/portal')
PROFILE_FIELDS=('assistant_name','robot_name','system_prompt','persona','greeting','language','voice','ai_model','speech_rate','ai_role','role_version')


def migrate_self_hosted():
    with connection() as db:
        if db.execute('SELECT 1 FROM schema_version WHERE version=6').fetchone():return
        import sqlite3
        from contextlib import closing
        from . import db as storage
        with closing(sqlite3.connect(storage.DB.parent/f'education-before-v6-{uuid4().hex}.sqlite3')) as backup:db.backup(backup)
        db.execute('BEGIN IMMEDIATE')
        for sql in (
            'CREATE TABLE self_hosted_links(robot_id TEXT PRIMARY KEY REFERENCES devices(id),agent_id TEXT NOT NULL UNIQUE,version INTEGER NOT NULL,enabled INTEGER NOT NULL,created_by TEXT NOT NULL,updated_at INTEGER NOT NULL)',
            'CREATE TABLE self_hosted_targets(candidate_id TEXT PRIMARY KEY REFERENCES config_candidates(id),agent_id TEXT NOT NULL,expected_revision INTEGER NOT NULL,link_version INTEGER NOT NULL,profile TEXT NOT NULL)',
            'CREATE TABLE self_hosted_jobs(candidate_id TEXT PRIMARY KEY REFERENCES config_candidates(id),robot_id TEXT NOT NULL,state TEXT NOT NULL,config_version INTEGER,server_revision INTEGER,server_hash TEXT,reason TEXT NOT NULL,updated_at INTEGER NOT NULL)',
        ):db.execute(sql)
        db.execute('INSERT INTO schema_version VALUES(6,?)',(int(time.time()),))


class SelfHostedAdapter:
    def __init__(self,link):
        self.link=dict(link)

    def request(self,method,path,body=None,allow_missing=False):
        origin=os.environ.get('WEWIN_AI_ORIGIN','http://127.0.0.1:8010').rstrip('/')
        parsed=urlsplit(origin)
        from ai_server.independence import reject_legacy
        try:reject_legacy(origin)
        except ValueError:raise HTTPException(503,'Legacy Cloud is forbidden as a WeWIN management origin')
        if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path or not (parsed.scheme=='https' or parsed.scheme=='http' and parsed.hostname in ('127.0.0.1','localhost')):
            raise HTTPException(503,'WeWIN AI origin phải là HTTPS hoặc loopback HTTP, không path/query/credential')
        try:key=Path(os.environ.get('WEWIN_AI_ADMIN_KEY_FILE',ROOT/'.secrets/ai_admin_key')).read_text(encoding='utf-8').strip()
        except OSError:raise HTTPException(503,'Chưa provision management key WeWIN AI phía server')
        if len(key)<32:raise HTTPException(503,'Management key WeWIN AI không hợp lệ')
        try:
            headers={'Authorization':'Bearer '+key}
            if self.link.get('owner_id'):headers.update({'X-WeWIN-Owner':self.link['owner_id'],'X-WeWIN-Tenant':self.link['tenant_id']})
            with httpx.Client(timeout=httpx.Timeout(120 if method=='PUT' else 6,connect=3),trust_env=False,follow_redirects=False) as client:
                response=client.request(method,origin+path,json=body,headers=headers)
            if response.status_code==404 and allow_missing:return None
            if response.status_code in (401,403):raise HTTPException(502,'WeWIN AI từ chối credential/quyền quản lý')
            if response.status_code==409:raise HTTPException(409,'Agent WeWIN AI đã đổi revision hoặc operation ID xung đột')
            if response.status_code==422:raise HTTPException(422,'WeWIN AI cần Agent đã Apply và ownership đúng trước khi cấp bootstrap')
            if response.status_code>=400:raise HTTPException(502,'WeWIN AI từ chối yêu cầu hoặc provider chưa sẵn sàng')
            result=response.json()
            if not isinstance(result,dict):raise HTTPException(502,'WeWIN AI phản hồi sai cấu trúc')
            return result
        except httpx.TimeoutException:raise HTTPException(504,'WeWIN AI timeout; chưa xác minh Apply. Không tự retry write.')
        except (httpx.HTTPError,ValueError):raise HTTPException(502,'Không đọc được phản hồi WeWIN AI; chưa xác minh Apply')

    def read(self):
        return self.request('GET','/v1/agents/'+self.link['agent_id'],allow_missing=True)

    def ensure_binding(self):
        if not self.link.get('device_id'):return
        device=self.request('GET','/v1/devices/'+self.link['device_id']+'/diagnostics',allow_missing=True)
        if device and device['agent_id']!=self.link['agent_id']:raise HTTPException(409,'Device–Agent binding khác đích Apply. Đối soát trước khi gửi cấu hình.')

    def capabilities(self):
        try:
            catalog=self.request('GET','/v1/catalog');ready=bool(catalog['models'] and catalog['voices'] and catalog['asr_model_configured'])
            reason='Đích Apply là WeWIN AI staging. Readback xác minh máy chủ; robot thật chưa được chuyển endpoint hoặc nghiệm thu.'
        except (HTTPException,KeyError):
            catalog={};ready=False;reason='WeWIN AI staging chưa sẵn sàng hoặc credential sai. Lưu Backend vẫn hoạt động; không tự gửi lại Apply.'
        return {'provider':'WeWIN AI staging','target_kind':'self_hosted','independent_platform':bool(self.link.get('owner_id')),'agent_reference':self.link['agent_id'],'connection_state':'staging_linked',
                'management_api_verified':ready,'read_supported':ready,'apply_supported':ready,'readback_supported':ready,'robot_acknowledged':False,
                'models':catalog.get('models',[]),'voices':catalog.get('voices',[]),'languages':catalog.get('languages',[]),'catalog_verified':bool(catalog),
                'credential_configured':bool(catalog),'reason':reason,'asr_language_scope':catalog.get('asr_language_scope','Chưa xác minh ASR'),
                'sync_states':['saved_backend_only','pending_apply','applying','server_applied_verified','device_session_verified','apply_failed','unsupported']}

    def prepare(self,payload):
        self.ensure_binding()
        current=self.read();catalog=self.request('GET','/v1/catalog')
        if not catalog.get('models') or not catalog.get('voices'):raise HTTPException(503,'Catalog WeWIN AI trống; chưa tạo đích Apply')
        payload=dict(payload)
        defaults=current['config'] if current else {'ai_model':catalog['models'][0]['id'],'voice':catalog['voices'][0]['id']}
        for key in ('ai_model','voice'):
            if not payload.get(key):payload[key]=defaults[key]
        profile={k:payload[k] for k in PROFILE_FIELDS}
        return payload,{'agent_id':self.link['agent_id'],'expected_revision':current['revision'] if current else 0,'link_version':self.link['version'],'profile':profile}

    def apply(self,profile,revision,operation_id):
        self.ensure_binding()
        return self.request('PUT','/v1/agents/'+self.link['agent_id'],{'config':profile,'expected_revision':revision,'operation_id':operation_id})


def linked_adapter(robot_id):
    with connection() as db:
        # Older migration fixtures may intentionally stop at v5.
        if not db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='self_hosted_links'").fetchone():return None
        row=db.execute('SELECT * FROM self_hosted_links WHERE robot_id=? AND enabled=1',(robot_id,)).fetchone()
    if row:
        from .managed_robots import record
        managed=record(robot_id)
        return SelfHostedAdapter({**dict(row),**({'owner_id':managed['owner_id'],'tenant_id':managed['tenant_id'],'device_id':managed['device_id']} if managed else {})})
    return None


def capture_target(db,candidate_id,adapter,payload):
    if not isinstance(adapter,SelfHostedAdapter):return payload
    try:resolved,target=adapter.prepare(payload)
    except HTTPException:return payload  # Keep local candidate/save usable during outages.
    db.execute('INSERT INTO self_hosted_targets VALUES(?,?,?,?,?)',(candidate_id,target['agent_id'],target['expected_revision'],target['link_version'],json.dumps(target['profile'],ensure_ascii=False)))
    return resolved


def apply_candidate(robot_id,body,auth,adapter):
    from .robot_workflow import checked_candidate
    from .robots import persist_config
    from ai_server.store import digest
    now=int(time.time())
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        row=checked_candidate(db,robot_id,body,auth)
        target=db.execute('SELECT * FROM self_hosted_targets WHERE candidate_id=?',(body.candidate_id,)).fetchone()
        link=db.execute('SELECT * FROM self_hosted_links WHERE robot_id=? AND enabled=1',(robot_id,)).fetchone()
        if not target or not link or target['agent_id']!=link['agent_id'] or target['link_version']!=link['version']:
            raise HTTPException(409,'Đích staging đã thay đổi hoặc chưa được preview. Tạo candidate mới.')
        job=db.execute('SELECT state,updated_at FROM self_hosted_jobs WHERE candidate_id=?',(body.candidate_id,)).fetchone()
        if job and job['state']=='applying' and now-job['updated_at']<180:raise HTTPException(409,'Apply đang chạy/chưa được đối soát; không gửi write đồng thời')
        db.execute('INSERT INTO self_hosted_jobs VALUES(?,?,?,NULL,NULL,NULL,?,?) ON CONFLICT(candidate_id) DO UPDATE SET state=excluded.state,reason=excluded.reason,updated_at=excluded.updated_at',(body.candidate_id,robot_id,'pending_apply','User confirmed staging target',now))
        audit(db,'self_hosted_pending_apply',auth['user_id'],robot_id,row['base_version'])
    profile=json.loads(target['profile']);payload=json.loads(row['payload'])
    with connection() as db:
        db.execute("UPDATE self_hosted_jobs SET state='applying' WHERE candidate_id=?",(body.candidate_id,))
        audit(db,'self_hosted_applying',auth['user_id'],robot_id)
    try:
        adapter.apply(profile,target['expected_revision'],'portal_'+body.candidate_id)
        observed=adapter.read()
        adapter.ensure_binding()
        if not observed or not observed.get('loaded') or observed.get('revision')!=target['expected_revision']+1 or observed.get('config')!=profile or observed.get('config_hash')!=digest(profile):
            raise HTTPException(502,'Readback khác candidate/revision hoặc runtime chưa nạp; không đánh dấu verified')
        with connection() as db:
            db.execute('BEGIN IMMEDIATE')
            checked_candidate(db,robot_id,body,auth)
            current_link=db.execute('SELECT * FROM self_hosted_links WHERE robot_id=? AND enabled=1',(robot_id,)).fetchone()
            if not current_link or current_link['version']!=target['link_version']:raise HTTPException(409,'Đích staging đổi trong lúc Apply; không ghi đè cấu hình local')
            result=persist_config(db,robot_id,payload,row['base_version'],auth,'apply_wewin_ai_server')
            db.execute("UPDATE robot_config SET sync_state='server_applied_verified' WHERE robot_id=?",(robot_id,))
            db.execute("UPDATE config_history SET sync_state='server_applied_verified' WHERE robot_id=? AND version=?",(robot_id,result['version']))
            db.execute('UPDATE config_candidates SET consumed=1 WHERE id=?',(body.candidate_id,))
            db.execute("UPDATE self_hosted_jobs SET state='server_applied_verified',config_version=?,server_revision=?,server_hash=?,reason='Runtime readback matched; physical robot not verified',updated_at=? WHERE candidate_id=?",(result['version'],observed['revision'],observed['config_hash'],int(time.time()),body.candidate_id))
            db.execute('INSERT INTO config_sync_history(robot_id,state,reason,at,actor) VALUES(?,?,?,?,?)',(robot_id,'server_applied_verified','WeWIN AI runtime readback; no physical device proof',int(time.time()),auth['user_id']))
            audit(db,'self_hosted_readback_verified',auth['user_id'],robot_id,result['version'])
        return {**result,'sync_state':'server_applied_verified','server_revision':observed['revision'],'server_applied':True,'cloud_applied':False,'robot_applied':False,'message':'WeWIN AI Server đã nạp cấu hình và readback khớp. Robot thật chưa được kết nối/xác minh.'}
    except HTTPException as exc:
        with connection() as db:
            db.execute("UPDATE self_hosted_jobs SET state='apply_failed',reason=?,updated_at=? WHERE candidate_id=?",(str(exc.detail)[:300],int(time.time()),body.candidate_id))
            audit(db,'self_hosted_apply_failed',auth['user_id'],robot_id)
        raise


class LinkConfirmation(BaseModel):
    model_config=ConfigDict(extra='forbid')
    confirmed: bool=False


@router.get('/robots/{rid}/self-hosted')
def get_link(rid:str,auth=Depends(session)):
    require_robot(rid,auth)
    if auth['role']!='admin':raise HTTPException(403,'Chỉ quản trị quản lý liên kết máy chủ')
    with connection() as db:row=db.execute('SELECT * FROM self_hosted_links WHERE robot_id=?',(rid,)).fetchone()
    adapter=linked_adapter(rid)
    health=None
    if adapter:
        try:health=adapter.request('GET','/health')
        except HTTPException:pass
    return {'link':dict(row) if row else None,'capabilities':adapter.capabilities() if adapter else None,'server_health':health,'device_verified':False}


@router.post('/robots/{rid}/self-hosted')
def enable_link(rid:str,body:LinkConfirmation,auth=Depends(administrator)):
    require_robot(rid,auth)
    from .cloud_config import limit_action
    limit_action(auth,'self_hosted_link',10)
    if not body.confirmed:raise HTTPException(422,'Cần xác nhận đích staging, không thay endpoint robot')
    with connection() as db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('INSERT OR IGNORE INTO devices VALUES(?,?,?)',(rid,'connector_registry',int(time.time())))
        db.execute('INSERT INTO self_hosted_links VALUES(?,?,1,1,?,?) ON CONFLICT(robot_id) DO UPDATE SET enabled=1,version=version+1,updated_at=excluded.updated_at',(rid,'wewin_'+rid,auth['user_id'],int(time.time())))
        audit(db,'link_self_hosted_staging',auth['user_id'],rid)
    return {'message':'Đã chọn đích WeWIN AI staging cho Portal. Chưa Apply, chưa thay endpoint hoặc mapping vật lý của robot.'}


@router.post('/robots/{rid}/self-hosted/disconnect')
def disable_link(rid:str,body:LinkConfirmation,auth=Depends(administrator)):
    require_robot(rid,auth)
    from .managed_robots import record
    if record(rid):raise HTTPException(409,'Robot WeWIN tự quản không tự quay về legacy Cloud. Dùng quản lý binding hoặc revoke.')
    from .cloud_config import limit_action
    limit_action(auth,'self_hosted_link',10)
    if not body.confirmed:raise HTTPException(422,'Cần xác nhận bỏ liên kết Portal')
    with connection() as db:
        db.execute('UPDATE self_hosted_links SET enabled=0,version=version+1 WHERE robot_id=?',(rid,))
        audit(db,'unlink_self_hosted_staging',auth['user_id'],rid)
    return {'message':'Đã bỏ liên kết staging trong Portal. Không xóa Agent hoặc thay robot.'}
