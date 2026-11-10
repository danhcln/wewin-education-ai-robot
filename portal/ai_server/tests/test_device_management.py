"""WeWIN bootstrap/ownership tests. Isolated DB, no physical device or Cloud."""
import asyncio
import hashlib
import json
import time
import sqlite3
from dataclasses import replace
from contextlib import closing
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch,AsyncMock
from fastapi import HTTPException
import httpx
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from ai_server.tests.test_service import ServiceFixture
from ai_server.device_management import BootstrapLogRedaction,PREFIX,origin
from ai_server.store import connect
from ai_server.settings import Settings
from ai_server.independence import reject_legacy
from ai_server.edge import create_edge


class ManagedDeviceTests(ServiceFixture):
    def setUp(self):
        super().setUp()
        self.scoped={**self.headers,'X-WeWIN-Owner':'owner-a','X-WeWIN-Tenant':'tenant-a'}
        response=self.client.put('/v1/agents/owned-agent',headers=self.scoped,json={'expected_revision':0,'operation_id':'owned-agent-operation-1234','config':self.profile})
        self.assertEqual(response.status_code,200)
        self.body={'device_id':'sim-owned-device','client_id':'owned-client-uuid','agent_id':'owned-agent','kind':'simulator','ownership_attested':True,'ownership_evidence':'Explicit isolated fixture ownership, not hardware evidence','confirmed':True,'ttl_seconds':3600}

    def provision(self):
        response=self.client.post('/v1/device-provisions',headers=self.scoped,json=self.body);self.assertEqual(response.status_code,200,response.text)
        self.receipt=response.json();self.url=self.receipt['bootstrap_url']
        return self.receipt

    def bootstrap(self,url=None,headers=None):
        return self.client.post(url or self.url,headers=headers or {'Device-Id':self.body['device_id'].upper(),'Client-Id':self.body['client_id'],'Activation-Version':'2'},json={'application':{'version':'fixture-1'}})

    def ws_headers(self,token):return {'Authorization':'Bearer '+token,'Device-Id':self.body['device_id'],'Client-Id':self.body['client_id'],'Protocol-Version':'1'}

    def diagnostic(self):return self.client.get('/v1/devices/'+self.body['device_id']+'/diagnostics',headers=self.scoped).json()

    def test_scoped_ownership_and_duplicate_reservation(self):
        denied=self.client.post('/v1/device-provisions',headers=self.headers,json=self.body);self.assertEqual(denied.status_code,403)
        other={**self.scoped,'X-WeWIN-Tenant':'tenant-b'}
        self.assertEqual(self.client.post('/v1/device-provisions',headers=other,json=self.body).status_code,403)
        self.assertEqual(self.client.get('/v1/agents',headers=other).json()['items'],[])
        self.provision()
        self.assertEqual(self.client.post('/v1/device-provisions',headers=self.scoped,json={**self.body,'device_id':self.body['device_id'].upper()}).status_code,409)
        self.assertEqual(self.client.post('/v1/devices',headers=self.headers,json={k:self.body[k] for k in ('device_id','client_id','agent_id')}).status_code,403)
        self.assertEqual(self.client.get('/v1/devices/'+self.body['device_id']+'/diagnostics',headers=other).status_code,403)

    def test_early_query_rejection_also_redacts_actual_server_scope(self):
        async def check():
            path=PREFIX+'private-bootstrap-capability-value-1234567890123'
            server_scope={'type':'http','asgi':{'version':'3.0','spec_version':'2.4'},'http_version':'1.1','method':'POST','scheme':'http','path':path,'raw_path':path.encode(),'query_string':b'token=private-query','root_path':'','headers':[],'server':('localhost',8010),'client':('127.0.0.1',9999)}
            messages=[]
            async def receive():return {'type':'http.request','body':b'','more_body':False}
            async def send(message):messages.append(message)
            await self.app(server_scope,receive,send)
            self.assertEqual(messages[0]['status'],400)
            self.assertNotIn('private-bootstrap',server_scope['path'])
            self.assertNotIn(b'private-query',server_scope['query_string'])
        asyncio.run(check())

    def test_secret_bootstrap_is_idempotent_without_vendor_activation_or_firmware(self):
        receipt=self.provision();first=self.bootstrap();self.assertEqual(first.status_code,200,first.text)
        second=self.bootstrap().json();self.assertEqual(first.json()['websocket']['token'],second['websocket']['token'])
        self.assertNotIn('firmware',second);self.assertNotIn('activation',second);self.assertFalse(second['wewin']['vendor_activation_emulated'])
        self.assertEqual(self.bootstrap(headers={'Device-Id':self.body['device_id'],'Client-Id':'incorrect-client'}).status_code,403)
        self.assertEqual(self.bootstrap(self.url[:-3]+'bad').status_code,403)
        with connect(self.settings) as db:
            stored=json.dumps([dict(r) for r in db.execute('SELECT * FROM managed_devices')]);stored+=json.dumps([dict(r) for r in db.execute('SELECT * FROM audit')])
        self.assertNotIn(receipt['bootstrap_url'].split('/')[-1],stored);self.assertNotIn(second['websocket']['token'],stored)
        self.assertNotIn('bootstrap_hash',json.dumps(self.diagnostic()));self.assertFalse(self.diagnostic()['online'])

    def test_online_means_authenticated_hello_and_revoke_blocks_bootstrap_and_reconnect(self):
        self.provision();token=self.bootstrap().json()['websocket']['token'];headers=self.ws_headers(token)
        with self.client.websocket_connect('/xiaozhi/v1/',headers=headers) as ws:
            self.assertFalse(self.diagnostic()['online'])
            ws.send_json({**self.hello(),'features':{}});ws.receive_json();self.assertTrue(self.diagnostic()['online'])
            result=self.client.post('/v1/devices/'+self.body['device_id']+'/revoke',headers=self.scoped,json={'confirmed':True});self.assertEqual(result.status_code,200)
            with self.assertRaises(WebSocketDisconnect):ws.receive_json()
        self.assertEqual(self.bootstrap().status_code,403)
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/xiaozhi/v1/',headers=headers):pass
        self.assertFalse(self.diagnostic()['online']);self.assertTrue(self.diagnostic()['sessions'][0]['ended_at'])

    def test_binding_cas_rotates_ws_and_resolves_same_owner_agent(self):
        self.provision();old=self.bootstrap().json()['websocket']['token']
        result=self.client.put('/v1/agents/second-agent',headers=self.scoped,json={'expected_revision':0,'operation_id':'second-agent-operation-123','config':self.profile});self.assertEqual(result.status_code,200)
        path='/v1/devices/'+self.body['device_id']+'/binding'
        body={'confirmed':True,'expected_binding_version':1,'agent_id':'second-agent'}
        self.assertEqual(self.client.post(path,headers=self.scoped,json=body).json()['binding_version'],2)
        self.assertEqual(self.client.post(path,headers=self.scoped,json=body).status_code,409)
        self.assertEqual(self.diagnostic()['agent_id'],'second-agent')
        fresh=self.bootstrap().json()['websocket']['token'];self.assertNotEqual(old,fresh)
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/xiaozhi/v1/',headers=self.ws_headers(old)):pass
        rotated=self.client.post('/v1/devices/'+self.body['device_id']+'/credentials/rotate',headers=self.scoped,json={'confirmed':True,'expected_binding_version':2});self.assertEqual(rotated.status_code,200)
        self.assertEqual(self.bootstrap().status_code,403)
        self.assertEqual(self.bootstrap(rotated.json()['bootstrap_url']).status_code,200)

    def test_expiry_and_lost_issuer_fail_closed(self):
        self.provision();token=self.bootstrap().json()['websocket']['token']
        issuer=self.settings.key_file.parent/'ai_device_issuer_key';original=issuer.read_bytes();issuer.unlink()
        try:self.assertEqual(self.bootstrap().status_code,503);self.assertFalse(issuer.exists())
        finally:issuer.write_bytes(original)
        with connect(self.settings) as db:db.execute('UPDATE managed_devices SET expires_at=?',(int(time.time())-5,))
        self.assertEqual(self.bootstrap().status_code,403)
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/xiaozhi/v1/',headers=self.ws_headers(token)):pass

    def test_sqlite_restore_preserves_scope_generation_and_revocation(self):
        from ai_server.app import create_app
        self.provision();token=self.bootstrap().json()['websocket']['token']
        rotated=self.client.post('/v1/devices/'+self.body['device_id']+'/credentials/rotate',headers=self.scoped,json={'confirmed':True,'expected_binding_version':1})
        self.assertEqual(rotated.status_code,200)
        self.assertEqual(self.client.post('/v1/devices/'+self.body['device_id']+'/revoke',headers=self.scoped,json={'confirmed':True}).status_code,200)
        restored=self.settings.db.parent/'restored.sqlite3'
        with connect(self.settings) as source,closing(sqlite3.connect(restored)) as destination:source.backup(destination)
        with TestClient(create_app(replace(self.settings,db=restored),self.app.state.providers)) as client:
            path='/v1/devices/'+self.body['device_id']+'/diagnostics'
            actual=client.get(path,headers=self.scoped).json()
            self.assertEqual(actual['binding_version'],2);self.assertTrue(actual['revoked']);self.assertFalse(actual['online'])
            self.assertEqual(client.get(path,headers={**self.scoped,'X-WeWIN-Owner':'wrong-owner'}).status_code,403)
            native={'Device-Id':self.body['device_id'],'Client-Id':self.body['client_id']}
            self.assertEqual(client.post(rotated.json()['bootstrap_url'],headers=native,json={}).status_code,403)
            with self.assertRaises(WebSocketDisconnect):
                with client.websocket_connect('/xiaozhi/v1/',headers=self.ws_headers(token)):pass

    def test_physical_gate_no_loopback_and_no_implicit_legacy_agent_claim(self):
        self.assertEqual(self.client.post('/v1/device-provisions',headers=self.scoped,json={**self.body,'kind':'physical'}).status_code,403)
        self.settings.real_devices=True;self.settings.trusted_tls_edge=True
        with self.assertRaises(HTTPException):origin(self.settings,'physical')
        self.assertEqual(self.apply().status_code,200)
        r=self.client.put('/v1/agents/fixture-agent',headers=self.scoped,json={'expected_revision':1,'operation_id':'claim-legacy-operation-123','config':self.profile})
        self.assertEqual(r.status_code,409)


class BoundaryTests(TestCase):
    def test_edge_timeout_is_explicit_and_never_falls_back(self):
        with TestClient(create_edge()) as client,patch('ai_server.edge.httpx.AsyncClient') as transport:
            upstream=transport.return_value.__aenter__=AsyncMock()
            upstream.return_value.post=AsyncMock(side_effect=httpx.ReadTimeout('private detail'))
            transport.return_value.__aexit__=AsyncMock(return_value=False)
            response=client.post(PREFIX+'a'*43,headers={'Device-Id':'fixture-device','Client-Id':'fixture-client'},json={})
            self.assertEqual(response.status_code,503)
            self.assertIn('no legacy Cloud fallback',response.json()['detail'])
            self.assertNotIn('private detail',response.text)

    def test_http_edge_does_not_trust_spoofed_tls_marker(self):
        with TestClient(create_edge()) as client,patch('ai_server.edge.httpx.AsyncClient') as transport:
            upstream=transport.return_value.__aenter__=AsyncMock()
            upstream.return_value.post=AsyncMock(return_value=httpx.Response(403,json={'detail':'TLS required'}))
            transport.return_value.__aexit__=AsyncMock(return_value=False)
            response=client.post(PREFIX+'a'*43,headers={'X-WeWIN-Edge-TLS':'1'},json={})
            self.assertEqual(response.status_code,403)
            self.assertEqual(upstream.return_value.post.call_args.kwargs['headers']['X-WeWIN-Edge-TLS'],'0')

    def test_legacy_endpoints_rejected_and_management_never_exposed_by_edge(self):
        for url in ('https://api.tenclass.net','wss://xiaozhi.me/xiaozhi/v1/','https://xiaozhi-api.tandev282.workers.dev/ota'):
            with self.assertRaises(ValueError):reject_legacy(url)
        with TestClient(create_edge()) as client:
            for path in ('/v1/agents','/v1/devices','/docs','/openapi.json'):self.assertEqual(client.get(path).status_code,404)
            self.assertFalse(client.get('/health').json()['management_routes_exposed'])

    def test_bootstrap_and_rejected_queries_are_redacted_from_server_scope(self):
        async def check():
            seen={}
            async def app(scope,receive,send):seen.update(scope)
            scope={'type':'http','path':PREFIX+'secret-value','raw_path':(PREFIX+'secret-value').encode(),'query_string':b'key=private'}
            await BootstrapLogRedaction(app)(scope,None,None)
            self.assertEqual(seen['path'],PREFIX+'secret-value');self.assertEqual(seen['query_string'],b'key=private')
            self.assertNotIn('secret-value',scope['path']);self.assertNotIn(b'private',scope['query_string'])
        asyncio.run(check())
