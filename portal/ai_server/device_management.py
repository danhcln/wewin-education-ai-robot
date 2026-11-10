"""WeWIN-owned enrollment; no vendor token, MAC-only activation or firmware OTA.

The bootstrap URL is a scoped secret delivered out-of-band after operator ownership
attestation. It is NOT hardware attestation or proven TanDev provisioning support.
Physical issuance stays gated; HTTPS/WSS/routable origins are mandatory for it.
"""
import base64
import hashlib
import hmac
import ipaddress
import json
import secrets
import time
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import HTTPException
from pydantic import BaseModel,ConfigDict,Field,field_validator
from .store import connect,audit
from .independence import reject_legacy

PREFIX='/xiaozhi/ota/bootstrap/'


class DeviceProvision(BaseModel):
    model_config=ConfigDict(extra='forbid')
    device_id:str=Field(min_length=6,max_length=100,pattern=r'^[a-zA-Z0-9_:-]+$')
    client_id:str=Field(min_length=6,max_length=100,pattern=r'^[a-zA-Z0-9_-]+$')
    agent_id:str=Field(min_length=1,max_length=120,pattern=r'^[a-zA-Z0-9_-]+$')
    kind:str=Field(default='simulator',pattern='^(simulator|physical)$')
    transport:str=Field(default='websocket',pattern='^(websocket|mqtt_udp)$')
    ownership_attested:bool=False
    ownership_evidence:str=Field(min_length=12,max_length=300)
    confirmed:bool=False
    ttl_seconds:int=Field(default=31536000,ge=300,le=31536000)

    @field_validator('device_id')
    @classmethod
    def canonical_id(cls,value):return value.lower()


class DeviceChange(BaseModel):
    model_config=ConfigDict(extra='forbid')
    confirmed:bool=False
    expected_binding_version:int=Field(ge=1)
    agent_id:str=Field(default='',max_length=120,pattern=r'^[a-zA-Z0-9_-]*$')


def scope(owner,tenant,required=False):
    if bool(owner)!=bool(tenant) or required and not owner:raise HTTPException(403,'Owner and tenant scope required')
    if any(len(v)>100 or not all(c.isalnum() or c in '_-' for c in v) for v in (owner,tenant)):raise HTTPException(403,'Invalid ownership scope')
    return owner,tenant


def agent_scope(db,agent_id,owner,tenant,mutation=False):
    row=db.execute('SELECT * FROM agent_owners WHERE agent_id=?',(agent_id,)).fetchone()
    if row and (mutation or owner) and (row['owner_id'],row['tenant_id'])!=(owner,tenant):raise HTTPException(403,'Agent owner/tenant mismatch')
    if owner and not row and db.execute('SELECT 1 FROM agents WHERE id=?',(agent_id,)).fetchone():raise HTTPException(409,'Legacy Agent has no verified WeWIN ownership; it is not implicitly claimed')
    return row


def issuer(settings):
    try:return _issuer(settings)
    except OSError:raise HTTPException(503,'Device issuer key unavailable; restore/provision its private file explicitly') from None


def _issuer(settings):
    path=settings.device_issuer_file
    path.parent.mkdir(parents=True,exist_ok=True)
    if not path.exists():
        with connect(settings) as db:
            if db.execute('SELECT 1 FROM managed_devices LIMIT 1').fetchone():raise HTTPException(503,'Restore the original device issuer key; never silently replace it')
        try:
            with path.open('x',encoding='utf-8') as stream:stream.write(secrets.token_urlsafe(48))
        except FileExistsError:pass
    key=path.read_bytes().strip()
    if len(key)<43:raise HTTPException(503,'Device issuer key unavailable')
    return key


def ws_token(settings,device,managed):
    material=json.dumps(['wewin-device-ws-v1',device['id'],device['client_id'],device['agent_id'],managed['owner_id'],managed['tenant_id'],managed['credential_nonce']],separators=(',',':')).encode()
    return base64.urlsafe_b64encode(hmac.new(issuer(settings),material,hashlib.sha256).digest()).decode().rstrip('=')


def origin(settings,kind):
    value=settings.device_origin.rstrip('/');parsed=urlsplit(value)
    try:reject_legacy(value)
    except ValueError as exc:raise HTTPException(503,str(exc))
    if parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment or not parsed.hostname or parsed.scheme not in ('http','https'):raise HTTPException(503,'Configure a plain WeWIN device origin without credentials/path')
    if kind=='physical':
        if not settings.real_devices or not settings.trusted_tls_edge:raise HTTPException(403,'Physical enrollment/cutover is disabled; separate approval and TLS edge required')
        try:loopback=ipaddress.ip_address(parsed.hostname).is_loopback or ipaddress.ip_address(parsed.hostname).is_unspecified
        except ValueError:loopback=parsed.hostname.lower() in ('localhost','localhost.localdomain')
        if parsed.scheme!='https' or loopback:raise HTTPException(503,'Physical devices require reachable HTTPS/WSS, never loopback discovery')
    return value


def owned_device(db,device_id,owner,tenant):
    row=db.execute('SELECT m.*,d.client_id,d.agent_id,d.kind,d.revoked FROM managed_devices m JOIN devices d ON d.id=m.device_id WHERE m.device_id=?',(device_id,)).fetchone()
    if not row:raise HTTPException(404,'Managed device not found')
    if (row['owner_id'],row['tenant_id'])!=(owner,tenant):raise HTTPException(403,'Device owner/tenant mismatch')
    return row


def binding_valid(db,device):
    row=db.execute('SELECT m.owner_id,m.tenant_id,m.expires_at,a.owner_id AS agent_owner,a.tenant_id AS agent_tenant FROM managed_devices m LEFT JOIN agent_owners a ON a.agent_id=? WHERE m.device_id=?',(device['agent_id'],device['id'])).fetchone()
    return not row and device['kind']=='simulator' or bool(row and row['expires_at']>=int(time.time()) and (row['owner_id'],row['tenant_id'])==(row['agent_owner'],row['agent_tenant']))


def tls_required(db,settings,device_id):
    pin=db.execute('SELECT requires_tls FROM device_transport_policy WHERE device_id=?',(device_id,)).fetchone()
    return settings.device_origin.startswith('https://') or bool(pin and pin['requires_tls'])


def provision(settings,body,owner,tenant):
    scope(owner,tenant,True);base=origin(settings,body.kind)
    if body.transport=='mqtt_udp':
        if body.kind!='simulator':raise HTTPException(403,'MQTT/UDP physical enrollment is disabled; legacy audio is unauthenticated')
        from .mqtt_udp import bootstrap_config
        try:bootstrap_config(settings,{'id':body.device_id,'client_id':body.client_id,'kind':body.kind},'validation-only')
        except ValueError as exc:raise HTTPException(503,str(exc))
    if not body.confirmed or not body.ownership_attested:raise HTTPException(422,'Explicit ownership attestation and provisioning confirmation required')
    bootstrap=secrets.token_urlsafe(32);nonce=secrets.token_hex(32);now=int(time.time())
    with connect(settings) as db:
        db.execute('BEGIN IMMEDIATE')
        if not agent_scope(db,body.agent_id,owner,tenant):raise HTTPException(422,'Apply an owned WeWIN Agent first')
        if db.execute('SELECT 1 FROM devices WHERE id=? OR lower(id)=? OR client_id=?',(body.device_id,body.device_id,body.client_id)).fetchone():raise HTTPException(409,'Device or client already registered; no implicit credential replacement')
        device={'id':body.device_id,'client_id':body.client_id,'agent_id':body.agent_id}
        managed={'owner_id':owner,'tenant_id':tenant,'credential_nonce':nonce}
        token=ws_token(settings,device,managed)
        db.execute('INSERT INTO devices VALUES(?,?,?,?,?,0)',(body.device_id,body.client_id,body.agent_id,hashlib.sha256(token.encode()).hexdigest(),body.kind))
        db.execute('INSERT INTO managed_devices VALUES(?,?,?,?,?,1,?,?,NULL,NULL,NULL)',(body.device_id,owner,tenant,hashlib.sha256(bootstrap.encode()).hexdigest(),nonce,now+body.ttl_seconds,now))
        db.execute('INSERT INTO device_transport_policy VALUES(?,?,?)',(body.device_id,int(base.startswith('https://')),base))
        db.execute('INSERT INTO device_protocols VALUES(?,?)',(body.device_id,body.transport))
        audit(db,'wewin_device_provisioned',body.device_id,json.dumps({'owner':owner,'tenant':tenant,'kind':body.kind,'ownership_evidence':body.ownership_evidence}))
    return {'device_id':body.device_id,'agent_id':body.agent_id,'owner_id':owner,'tenant_id':tenant,'binding_version':1,'state':'provisioned_pending_authentication','bootstrap_url':base+PREFIX+bootstrap,'display_once':True,'expires_at':now+body.ttl_seconds,'physical_verified':False,'credential_type':'scoped_revocable_shared_secret_not_hardware_attestation'}


def diagnostic(settings,device_id,owner,tenant,connections):
    with connect(settings) as db:
        row=dict(owned_device(db,device_id,owner,tenant));row.pop('bootstrap_hash');row.pop('credential_nonce')
        history=[dict(r) for r in db.execute('SELECT id,kind,started_at,ended_at FROM sessions WHERE device_id=? ORDER BY started_at DESC LIMIT 20',(device_id,))]
        recent=db.execute('SELECT action,at FROM audit WHERE target=? ORDER BY id DESC LIMIT 15',(device_id,)).fetchall()
        declared=db.execute('SELECT payload FROM device_declarations WHERE device_id=?',(device_id,)).fetchone()
        policy=db.execute('SELECT requires_tls,device_origin FROM device_transport_policy WHERE device_id=?',(device_id,)).fetchone()
    active=connections.get(device_id)
    online=bool(active and not row['revoked'] and row['expires_at']>=int(time.time()) and active.get('hello_verified') and active['socket'].application_state.name=='CONNECTED')
    row.update(online=online,connection_evidence='authenticated_gateway_socket' if online else 'no_verified_socket',last_message_at=active.get('last_message_at') if active else None,sessions=history,audit=[dict(r) for r in recent],physical_verified=False,bootstrap_supported=True,vendor_activation_emulated=False)
    row['declared_capabilities']=json.loads(declared['payload']) if declared else {}
    row['capabilities_evidence']='client_declared_not_hardware_verified'
    row['transport_policy']=dict(policy) if policy else None
    return row


async def bootstrap(request,settings,secret):
    if request.headers.get('origin'):raise HTTPException(403,'Native device bootstrap only')
    if not 40<=len(secret)<=80:raise HTTPException(403,'Bootstrap authentication failed')
    with connect(settings) as db:
        row=db.execute('SELECT m.*,d.id,d.client_id,d.agent_id,d.kind,d.revoked FROM managed_devices m JOIN devices d ON d.id=m.device_id WHERE m.bootstrap_hash=?',(hashlib.sha256(secret.encode()).hexdigest(),)).fetchone()
        if not row or row['revoked'] or row['expires_at']<int(time.time()) or row['id']!=request.headers.get('device-id','').lower() or row['client_id']!=request.headers.get('client-id',''):raise HTTPException(403,'Bootstrap authentication failed')
        base=origin(settings,row['kind'])
        pin=db.execute('SELECT requires_tls,device_origin FROM device_transport_policy WHERE device_id=?',(row['id'],)).fetchone()
        if pin and pin['requires_tls'] and base!=pin['device_origin']:raise HTTPException(503,'Pinned TLS origin changed; explicit approved TLS credential rotation required')
        if base.startswith('https://'):
            db.execute('INSERT INTO device_transport_policy VALUES(?,1,?) ON CONFLICT(device_id) DO UPDATE SET requires_tls=1,device_origin=excluded.device_origin',(row['id'],base))
        if row['kind']=='physical' and (request.client.host!='127.0.0.1' or request.headers.get('x-wewin-edge-tls')!='1'):raise HTTPException(403,'Physical bootstrap requires the trusted TLS device edge')
        if not binding_valid(db,row):raise HTTPException(403,'Device-Agent ownership mismatch')
        version=request.headers.get('activation-version','1')
        if version not in ('1','2'):raise HTTPException(422,'Unsupported declared activation version')
        # Metadata only. We do not pretend to perform TanDev eFuse/HMAC activation.
        data=bytearray()
        async for chunk in request.stream():
            data.extend(chunk)
            if len(data)>16384:raise HTTPException(413,'OTA request too large')
        try:payload=json.loads(data or b'{}')
        except ValueError:raise HTTPException(422,'Invalid OTA JSON')
        if not isinstance(payload,dict):raise HTTPException(422,'OTA JSON object required')
        app=payload.get('application') or {};device_version=str(app.get('version',''))[:80] if isinstance(app,dict) else ''
        # Store only bounded, explicitly declared transport/audio capabilities,
        # never the full vendor payload (which can contain identifiers/secrets).
        capabilities=payload.get('capabilities',{})
        declared={k:v for k,v in capabilities.items() if k in ('websocket','mqtt','mcp','audio_format','sample_rate','channels','frame_duration') and isinstance(v,(bool,int,str)) and len(str(v))<=80} if isinstance(capabilities,dict) else {}
        token=ws_token(settings,row,row)
        if hashlib.sha256(token.encode()).hexdigest()!=db.execute('SELECT token_hash FROM devices WHERE id=?',(row['id'],)).fetchone()[0]:raise HTTPException(503,'Issuer generation mismatch; explicit credential rotation required')
        db.execute('UPDATE managed_devices SET last_bootstrap_at=?,device_version=?,activation_version=? WHERE device_id=?',(int(time.time()),device_version,version,row['id']))
        db.execute('INSERT INTO device_declarations VALUES(?,?,?) ON CONFLICT(device_id) DO UPDATE SET payload=excluded.payload,observed_at=excluded.observed_at',(row['id'],json.dumps(declared),int(time.time())))
        audit(db,'wewin_bootstrap_authenticated',row['id'],'WeWIN secret possession; no vendor activation/firmware delivery')
        choice=db.execute('SELECT transport FROM device_protocols WHERE device_id=?',(row['id'],)).fetchone()
        mqtt_config=None
        if choice and choice[0]=='mqtt_udp':
            from .mqtt_udp import bootstrap_config
            try:mqtt_config=bootstrap_config(settings,row,token)
            except ValueError as exc:raise HTTPException(503,str(exc))
    response={'server_time':{'timestamp':int(time.time()*1000),'timezone_offset':420},'wewin':{'firmware_delivery':False,'vendor_activation_emulated':False,'kind':row['kind']}}
    if mqtt_config:response['mqtt']=mqtt_config
    else:response['websocket']={'url':base.replace('https://','wss://').replace('http://','ws://')+'/xiaozhi/v1/','token':token,'version':1}
    return response


async def change(settings,device_id,body,owner,tenant,connections,rotate=False):
    scope(owner,tenant,True)
    if not body.confirmed:raise HTTPException(422,'Explicit device change confirmation required')
    secret=secrets.token_urlsafe(32) if rotate else None
    with connect(settings) as db:
        db.execute('BEGIN IMMEDIATE');row=owned_device(db,device_id,owner,tenant)
        if row['revoked']:raise HTTPException(409,'Revoked device cannot be rebound or reactivated')
        base=origin(settings,row['kind'])
        if tls_required(db,settings,device_id) and not base.startswith('https://'):raise HTTPException(503,'Managed TLS credentials cannot downgrade to plaintext')
        if row['binding_version']!=body.expected_binding_version:raise HTTPException(409,'Device binding/credential version conflict')
        target=body.agent_id or row['agent_id']
        if not agent_scope(db,target,owner,tenant):raise HTTPException(422,'Owned target Agent required')
        nonce=secrets.token_hex(32);device={'id':device_id,'client_id':row['client_id'],'agent_id':target}
        token=ws_token(settings,device,{'owner_id':owner,'tenant_id':tenant,'credential_nonce':nonce})
        db.execute('UPDATE devices SET agent_id=?,token_hash=? WHERE id=?',(target,hashlib.sha256(token.encode()).hexdigest(),device_id))
        db.execute('UPDATE managed_devices SET credential_nonce=?,binding_version=binding_version+1 WHERE device_id=?',(nonce,device_id))
        db.execute('INSERT INTO device_transport_policy VALUES(?,?,?) ON CONFLICT(device_id) DO UPDATE SET requires_tls=excluded.requires_tls,device_origin=excluded.device_origin',(device_id,int(base.startswith('https://')),base))
        if rotate:db.execute('UPDATE managed_devices SET bootstrap_hash=?,expires_at=?,last_bootstrap_at=NULL WHERE device_id=?',(hashlib.sha256(secret.encode()).hexdigest(),int(time.time())+(86400 if row['kind']=='simulator' else 31536000),device_id))
        audit(db,'wewin_device_credentials_rotated' if rotate else 'wewin_device_agent_rebound',device_id,json.dumps({'agent':target,'owner':owner,'binding_version':row['binding_version']+1}))
        result={'device_id':device_id,'agent_id':target,'binding_version':row['binding_version']+1,'physical_verified':False}
    active=connections.get(device_id)
    if active:await active['socket'].close(code=1008)
    if secret:result.update(bootstrap_url=base+PREFIX+secret,display_once=True)
    return result


class BootstrapLogRedaction:
    """Sanitize server-owned ASGI scope while routing on a private original copy.
    Upstream proxies must also suppress/redact this credential-bearing URI.
    """
    def __init__(self,app):self.app=app
    async def __call__(self,scope,receive,send):
        sensitive=scope['type'] in ('http','websocket') and (scope.get('path','').startswith(PREFIX) or scope.get('query_string'))
        if sensitive:
            routed=dict(scope)
            if scope.get('path','').startswith(PREFIX):scope['path']=PREFIX+'[REDACTED]';scope['raw_path']=scope['path'].encode()
            if scope.get('query_string'):scope['query_string']=b'[REDACTED]'
            await self.app(routed,receive,send)
        else:await self.app(scope,receive,send)
