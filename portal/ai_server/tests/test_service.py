"""Isolated service/protocol tests. FakeProviders are explicit test doubles."""
import asyncio
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch,AsyncMock,MagicMock
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from ai_server.app import create_app
from ai_server.settings import Settings
from ai_server.audio import encode_audio,OpusInput,SpeechBoundary
from ai_server.providers import spoken_message,ProviderError,Providers
from ai_server.mcp_server import dispatch
from ai_server.mcp_client import MCPClient
import numpy as np


class FakeProviders:
    asr=None;tts=None
    turn_slots=None
    async def catalog(self):return {'models':[{'id':'fixture-model','name':'fixture'}],'voices':[{'id':'F1','name':'fixture'}],'languages':[{'id':'en-US','name':'English'}],'asr_model_configured':True}
    async def load(self):self.asr=object();self.tts=object()


class ServiceFixture(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        root=Path(self.tmp.name);key=root/'key';key.write_text('test-only-ai-management-key-1234567890')
        self.settings=Settings(db=root/'ai.sqlite3',key_file=key,connector_db=root/'knowledge.sqlite3')
        self.app=create_app(self.settings,FakeProviders());self.client=TestClient(self.app)
        self.client.__enter__();self.addCleanup(self.client.__exit__,None,None,None)
        self.headers={'Authorization':'Bearer '+key.read_text()}
        self.profile={'ai_model':'fixture-model','voice':'F1','system_prompt':'Teach English','greeting':'Hello Win','language':'en-US'}

    def apply(self,revision=0,operation='fixture-operation-12345',profile=None):
        return self.client.put('/v1/agents/fixture-agent',json={'expected_revision':revision,'operation_id':operation,'config':profile or self.profile},headers=self.headers)

    def register(self):
        self.assertEqual(self.apply().status_code,200)
        result=self.client.post('/v1/devices',json={'device_id':'fixture-simulator','client_id':'fixture-client','agent_id':'fixture-agent'},headers=self.headers)
        self.assertEqual(result.status_code,200)
        return {'Authorization':'Bearer '+result.json()['device_token'],'Device-Id':'fixture-simulator','Client-Id':'fixture-client','Protocol-Version':'1'}

    def hello(self,rate=16000):return {'type':'hello','version':1,'transport':'websocket','features':{'mcp':True},'audio_params':{'format':'opus','sample_rate':rate,'channels':1,'frame_duration':60}}


class ServiceTests(ServiceFixture):
    def test_management_auth_and_no_factory_activation(self):
        self.assertEqual(self.client.get('/v1/catalog').status_code,401)
        self.assertEqual(self.client.get('/v1/catalog?token=not-allowed',headers=self.headers).status_code,400)
        self.assertEqual(self.client.post('/xiaozhi/ota/',headers={'Device-Id':'unknown','Client-Id':'unknown'}).status_code,403)
        self.assertFalse(self.client.get('/health').json()['firmware_delivery'])

    def test_runtime_revision_readback_conflict_and_idempotency(self):
        first=self.apply();self.assertEqual(first.status_code,200)
        read=self.client.get('/v1/agents/fixture-agent',headers=self.headers).json()
        self.assertTrue(read['loaded']);self.assertEqual(read['state'],'server_applied_verified');self.assertFalse(read['device_verified'])
        self.assertEqual(read['config']['system_prompt'],'Teach English')
        self.assertEqual(self.apply().json()['revision'],1)
        self.assertEqual(self.apply(operation='different-operation-12345').status_code,409)
        self.assertEqual(self.apply(profile={**self.profile,'greeting':'conflicting replay'}).status_code,409)

    def test_catalog_validation_and_controlled_restore(self):
        self.assertEqual(self.apply(profile={**self.profile,'ai_model':'invented'}).status_code,422)
        self.assertEqual(self.apply().status_code,200)
        self.assertEqual(self.apply(1,'second-operation-12345',{**self.profile,'greeting':'second'}).status_code,200)
        self.assertEqual(self.apply(2,'restore-operation-12345').json()['revision'],3)
        self.assertEqual(len(self.client.get('/v1/agents/fixture-agent/history',headers=self.headers).json()['items']),3)

    def test_device_auth_discovery_and_physical_enrollment_gate(self):
        headers=self.register()
        denied=self.client.post('/v1/devices',json={'device_id':'physical-device','client_id':'physical-client','agent_id':'fixture-agent','kind':'physical'},headers=self.headers)
        self.assertEqual(denied.status_code,403)
        discovery=self.client.post('/xiaozhi/ota/',headers=headers).json()
        self.assertEqual(discovery['firmware']['url'],'');self.assertNotIn('mqtt',discovery)
        self.assertEqual(discovery['websocket']['version'],1)
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/xiaozhi/v1/',headers={**headers,'Client-Id':'wrong-client'}):pass

    def test_device_list_masks_token_and_revocation_prevents_reconnect(self):
        headers=self.register()
        listed=self.client.get('/v1/devices',headers=self.headers).json()
        self.assertNotIn('token',json.dumps(listed))
        self.assertEqual(self.client.get('/v1/agents',headers=self.headers).json()['items'][0]['id'],'fixture-agent')
        self.assertEqual(self.client.post('/v1/devices/fixture-simulator/revoke',json={'confirmed':False},headers=self.headers).status_code,422)
        with self.client.websocket_connect('/xiaozhi/v1/',headers=headers) as ws:
            ws.send_json(self.hello());ws.receive_json();ws.receive_json()
            self.assertEqual(self.client.post('/v1/devices/fixture-simulator/revoke',json={'confirmed':True},headers=self.headers).status_code,200)
            with self.assertRaises(WebSocketDisconnect):ws.receive_json()
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/xiaozhi/v1/',headers=headers):pass

    def test_provider_failure_does_not_create_agent_and_timeout_has_no_fallback(self):
        with patch.object(self.app.state.providers,'load',new=AsyncMock(side_effect=ProviderError('fixture provider unavailable'))):
            self.assertEqual(self.apply().status_code,503)
        self.assertEqual(self.client.get('/v1/agents',headers=self.headers).json()['items'],[])
        from httpx import ReadTimeout
        async def check():
            with patch('ai_server.providers.httpx.AsyncClient') as client:
                client.return_value.__aenter__.return_value.post=AsyncMock(side_effect=ReadTimeout('private upstream detail'))
                failure=MagicMock();failure.__aenter__=AsyncMock(side_effect=ReadTimeout('private upstream detail'))
                client.return_value.__aenter__.return_value.stream=MagicMock(return_value=failure)
                with self.assertRaises(ProviderError) as exc:
                    await Providers(self.settings).llm([{'role':'system','content':'fixture'},{'role':'user','content':'Test question'}],'fixture-model')
                self.assertNotIn('private upstream detail',str(exc.exception))
        asyncio.run(check())

    def test_websocket_hello_mcp_discovery_and_reconnect(self):
        headers=self.register()
        for _ in range(2):
            with self.client.websocket_connect('/xiaozhi/v1/',headers=headers) as ws:
                ws.send_json(self.hello());hello=ws.receive_json();self.assertEqual(hello['type'],'hello')
                rpc=ws.receive_json();self.assertEqual(rpc['payload']['method'],'initialize')
                ws.send_json({'type':'mcp','payload':{'jsonrpc':'2.0','id':1,'result':{'capabilities':{'tools':{}}}}})
                self.assertEqual(ws.receive_json()['payload']['method'],'notifications/initialized')
                self.assertEqual(ws.receive_json()['payload']['method'],'tools/list')
                ws.send_json({'type':'abort'});self.assertEqual(ws.receive_json()['state'],'stop')
        result=self.client.get('/v1/agents/fixture-agent/evidence',headers=self.headers).json()
        self.assertFalse(result['device_session_verified'])
        with closing(sqlite3.connect(self.settings.db)) as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM sessions WHERE kind="simulator" AND ended_at IS NOT NULL').fetchone()[0],2)

    def test_unsupported_binary_version_and_audio_format_are_rejected(self):
        headers=self.register()
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/xiaozhi/v1/',headers={**headers,'Protocol-Version':'2'}):pass
        with self.client.websocket_connect('/xiaozhi/v1/',headers=headers) as ws:
            ws.send_json(self.hello(48000))
            with self.assertRaises(WebSocketDisconnect):ws.receive_json()

    def test_native_opus_encode_decode_60ms_without_ai_fixture(self):
        wave=np.sin(np.arange(16000*.18)*2*np.pi*440/16000).astype(np.float32)*.1
        frames=encode_audio(wave,16000,16000)
        pcm=b''.join(OpusInput().decode(frame) for frame in frames)
        self.assertEqual(len(frames),3);self.assertEqual(len(pcm),5760)
        self.assertGreater(np.max(np.abs(np.frombuffer(pcm,dtype='<i2'))),100)

    def test_reasoning_and_incomplete_llm_output_never_reaches_tts(self):
        self.assertEqual(spoken_message({'content':'private reasoning</think> Final answer.'},'stop')['content'],'Final answer.')
        with self.assertRaises(ProviderError):spoken_message({'content':'unfinished reasoning'},'length')
        with self.assertRaises(ProviderError):spoken_message({'content':'<think>not done'},'stop')
        self.assertNotIn('thinking',spoken_message({'content':'final','thinking':'private'},'stop'))

    def test_vad_silence_does_not_invent_voice(self):
        boundary=SpeechBoundary()
        self.assertFalse(any(boundary.finished(b'\0'*1920) for _ in range(30)))

    def test_read_only_mcp_dispatch_and_real_stdio_transport(self):
        with closing(sqlite3.connect(self.settings.connector_db)) as conn,conn:
            conn.executescript("CREATE TABLE public_pages(id INTEGER PRIMARY KEY,title,url,content);CREATE VIRTUAL TABLE pages_fts USING fts5(content);INSERT INTO public_pages VALUES(1,'WeWIN courses','https://wewin.edu.vn/','WeWIN Cambridge information');INSERT INTO pages_fts(rowid,content) VALUES(1,'WeWIN Cambridge information');")
        response=dispatch({'method':'tools/call','params':{'name':'wewin_search','arguments':{'query':'Cambridge'}}},self.settings)
        self.assertIn('WeWIN courses',response['content'][0]['text'])
        with closing(sqlite3.connect(self.settings.connector_db)) as conn,conn:
            conn.execute("INSERT INTO public_pages VALUES(2,'Internal','https://wewin.edu.vn/internal','Cambridge confidential staff notes')")
            conn.execute("INSERT INTO pages_fts(rowid,content) VALUES(2,'Cambridge confidential staff notes')")
        response=dispatch({'method':'tools/call','params':{'name':'wewin_search','arguments':{'query':'Cambridge'}}},self.settings)
        self.assertNotIn('confidential',response['content'][0]['text'])
        with self.assertRaises(ValueError):dispatch({'method':'tools/call','params':{'name':'speaker.bluetooth','arguments':{'action':'connect'}}},self.settings)
        async def check():
            async with MCPClient(self.settings) as client:
                self.assertEqual(len((await client.request('tools/list'))['tools']),3)
                result=await client.request('tools/call',{'name':'wewin_test_connection','arguments':{}})
                self.assertIn('WeWIN MCP OK',result['content'][0]['text'])
        asyncio.run(check())
