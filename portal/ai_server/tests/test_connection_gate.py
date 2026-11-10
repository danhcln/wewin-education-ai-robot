"""Compatibility/security contracts, explicit fixtures and no real robot."""
import json
from unittest.mock import patch,AsyncMock
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
import httpx
from ai_server.tests.test_service import ServiceFixture
from ai_server.edge import create_edge
from ai_server.device_management import PREFIX


class CompatibilityTests(ServiceFixture):
    def test_tls_pin_survives_http_restart_configuration_and_requires_explicit_rotation(self):
        from ai_server.store import migrate
        self.settings.device_origin='https://192.168.2.10:8014';self.provision()
        token=self.client.post(self.url,headers=self.native,json={}).json()['websocket']['token']
        self.settings.device_origin='http://127.0.0.1:8010';migrate(self.settings)
        self.assertEqual(self.client.post(self.url,headers=self.native,json={}).status_code,503)
        self.assertEqual(self.client.post('/v1/devices/gate-device/credentials/rotate',headers=self.scoped,json={'confirmed':True,'expected_binding_version':1}).status_code,503)
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/xiaozhi/v1/',headers={**self.native,'Authorization':'Bearer '+token}):pass
        self.settings.device_origin='https://new-owned-staging.invalid:8014'
        self.assertEqual(self.client.post(self.url,headers=self.native,json={}).status_code,503)
        rotated=self.client.post('/v1/devices/gate-device/credentials/rotate',headers=self.scoped,json={'confirmed':True,'expected_binding_version':1});self.assertEqual(rotated.status_code,200)
        self.assertEqual(self.client.post(rotated.json()['bootstrap_url'],headers=self.native,json={}).status_code,200)

    def provision(self):
        self.scoped={**self.headers,'X-WeWIN-Owner':'gate-owner','X-WeWIN-Tenant':'gate-tenant'}
        self.assertEqual(self.client.put('/v1/agents/gate-agent',headers=self.scoped,json={'config':self.profile,'operation_id':'gate-create-operation-1234','expected_revision':0}).status_code,200)
        self.body={'device_id':'gate-device','client_id':'gate-client','agent_id':'gate-agent','kind':'simulator','ownership_attested':True,'ownership_evidence':'Owned isolated compatibility fixture','confirmed':True}
        r=self.client.post('/v1/device-provisions',headers=self.scoped,json=self.body);self.assertEqual(r.status_code,200);self.url=r.json()['bootstrap_url']
        self.native={'Device-Id':'gate-device','Client-Id':'gate-client','Activation-Version':'2'}

    def test_ota_contract_no_firmware_no_vendor_activation_and_bounded_metadata(self):
        self.provision();r=self.client.post(self.url,headers=self.native,json={'application':{'version':'fixture-2.5.3'},'capabilities':{'mcp':True,'sample_rate':16000,'private_secret':'never-persist-this-field'}})
        self.assertEqual(r.status_code,200);body=r.json();self.assertEqual(set(body),{'server_time','websocket','wewin'})
        self.assertEqual(body['websocket']['version'],1);self.assertNotIn('firmware',body);self.assertNotIn('activation',body)
        self.assertEqual(r.headers['cache-control'],'no-store')
        diag=self.client.get('/v1/devices/gate-device/diagnostics',headers=self.scoped).json()
        self.assertEqual(diag['device_version'],'fixture-2.5.3');self.assertEqual(diag['declared_capabilities'],{'mcp':True,'sample_rate':16000})
        self.assertNotIn('never-persist',json.dumps(diag))

    def test_bad_bootstrap_never_silently_downgrades_activation_or_browser_origin(self):
        self.provision()
        for body in ([],None,'not-an-object'):
            self.assertEqual(self.client.post(self.url,headers=self.native,content=json.dumps(body)).status_code,422)
        self.assertEqual(self.client.post(self.url,headers={**self.native,'Activation-Version':'3'},json={}).status_code,422)
        self.assertEqual(self.client.post(self.url,headers={**self.native,'Origin':'https://untrusted.invalid'},json={}).status_code,403)
        self.assertEqual(self.client.post(self.url,headers=self.native,content=b'x'*17000).status_code,413)
        self.assertEqual(self.client.get(self.url).status_code,405)

    def test_managed_https_origin_refuses_plaintext_ws_even_with_valid_bearer(self):
        self.provision();self.settings.device_origin='https://192.168.2.10:8014';self.settings.trusted_tls_edge=True
        result=self.client.post(self.url,headers=self.native,json={}).json()
        headers={**self.native,'Protocol-Version':'1','Authorization':'Bearer '+result['websocket']['token']}
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/xiaozhi/v1/',headers=headers):pass

    def test_edge_withholds_secret_on_tls_origin_mismatch_or_http_downgrade(self):
        for base,target,expected in [('http://192.168.2.10:8013','wss://192.168.2.10:8014/xiaozhi/v1/',426),('https://192.168.2.10:8014','ws://192.168.2.10:8013/xiaozhi/v1/',502),('https://192.168.2.10:8014','wss://other.invalid/xiaozhi/v1/',502)]:
            with TestClient(create_edge(),base_url=base) as client,patch('ai_server.edge.httpx.AsyncClient') as transport:
                upstream=transport.return_value.__aenter__=AsyncMock();transport.return_value.__aexit__=AsyncMock(return_value=False)
                upstream.return_value.post=AsyncMock(return_value=httpx.Response(200,json={'websocket':{'url':target,'token':'private-fixture-bearer'}}))
                response=client.post(PREFIX+'a'*43,json={});self.assertEqual(response.status_code,expected)
                self.assertNotIn('private-fixture-bearer',response.text)
