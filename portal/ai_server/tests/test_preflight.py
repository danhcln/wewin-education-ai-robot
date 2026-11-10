"""Protocol robustness with explicit AI doubles, real native Opus and isolated DB.
These tests do not certify TanDev firmware, a loudspeaker or educational quality.
"""
import asyncio
import json
import sqlite3
import threading
from contextlib import closing
from unittest.mock import patch,AsyncMock
import numpy as np
from starlette.websockets import WebSocketDisconnect
from ai_server.audio import encode_audio
from ai_server.mcp_client import MCPClient
from ai_server.tests import test_service as fixtures


class SpeechDouble(fixtures.FakeProviders):
    def __init__(self):
        self.turn_slots=asyncio.Semaphore(1);self.messages=[];self.delay=0;self.fail=False;self.started=threading.Event()
    async def llm(self,messages,model):
        self.messages.append(messages)
        self.started.set()
        if self.delay:await asyncio.sleep(self.delay)
        if self.fail:raise RuntimeError('TEST failure private detail')
        return {'content':'Teacher answer' if 'Teach English' in messages[0]['content'] else 'New role answer'}
    async def transcribe(self,pcm,language=None):return 'Synthetic test utterance'
    async def synthesize(self,text,profile):
        return np.sin(np.arange(2880)*2*np.pi*440/24000).astype(np.float32)*.1,24000


class PreflightTests(fixtures.ServiceFixture):
    def setUp(self):
        super().setUp();self.speech=SpeechDouble()
        self.provider_patch=patch.multiple(self.app.state.providers,turn_slots=self.speech.turn_slots,llm=self.speech.llm,transcribe=self.speech.transcribe,synthesize=self.speech.synthesize,create=True)
        self.provider_patch.start();self.addCleanup(self.provider_patch.stop)

    def open(self,headers):
        ws=self.client.websocket_connect('/xiaozhi/v1/',headers=headers)
        ws.__enter__();self.addCleanup(ws.__exit__,None,None,None)
        ws.send_json({**self.hello(),'features':{}});hello=ws.receive_json()
        return ws,hello

    def receive_turn(self,ws):
        events=[];frames=[]
        for _ in range(20):
            message=ws.receive()
            if message.get('bytes') is not None:frames.append(message['bytes']);continue
            event=json.loads(message['text']);events.append(event)
            if event.get('type')=='tts' and event.get('state')=='stop':return events,frames
        self.fail('Missing stop')

    def test_text_role_revision_and_history_boundary(self):
        ws,hello=self.open(self.register())
        for text in ('First question','Follow up'):
            ws.send_json({'type':'listen','state':'detect','text':text,'session_id':hello['session_id']})
            events,frames=self.receive_turn(ws);self.assertEqual(len(frames),2)
            self.assertEqual(next(e for e in events if e['type']=='wewin_config')['revision'],1)
        self.assertEqual(len(self.speech.messages[1]),4)
        self.assertEqual(self.apply(1,'new-role-operation-12345',{**self.profile,'system_prompt':'Be a course advisor'}).status_code,200)
        ws.send_json({'type':'listen','state':'detect','text':'New question'})
        events,_=self.receive_turn(ws)
        self.assertEqual(next(e for e in events if e['type']=='wewin_config')['revision'],2)
        self.assertEqual(len(self.speech.messages[2]),2)
        self.assertIn('New role answer',json.dumps(events))

    def test_opus_manual_uplink_downlink_and_stop(self):
        ws,_=self.open(self.register());ws.send_json({'type':'listen','state':'start','mode':'manual'})
        for frame in encode_audio(np.ones(2880,dtype=np.float32)*.1,16000,16000):ws.send_bytes(frame)
        ws.send_json({'type':'listen','state':'stop'})
        events,frames=self.receive_turn(ws)
        self.assertEqual(len(frames),2);self.assertIn('Synthetic test utterance',json.dumps(events))
        self.assertEqual([e['state'] for e in events if e['type']=='tts'],['start','sentence_start','stop'])

    def test_inflight_turn_keeps_snapshot_next_turn_loads_new_role(self):
        ws,_=self.open(self.register());self.speech.delay=.3
        ws.send_json({'type':'listen','state':'detect','text':'Question before role switch'})
        self.assertTrue(self.speech.started.wait(5))
        self.assertEqual(self.apply(1,'mid-turn-role-operation-123',{**self.profile,'system_prompt':'New course advisor role'}).status_code,200)
        events,_=self.receive_turn(ws)
        self.assertEqual(next(e for e in events if e['type']=='wewin_config')['revision'],1)
        ws.send_json({'type':'listen','state':'detect','text':'Question after role switch'})
        events,_=self.receive_turn(ws)
        self.assertEqual(next(e for e in events if e['type']=='wewin_config')['revision'],2)
        self.assertIn('New role answer',json.dumps(events))

    def test_wrong_credential_origin_query_and_duplicate_session_are_denied(self):
        headers=self.register()
        for path,extra in (('/xiaozhi/v1/',{'Authorization':'Bearer invalid'}),('/xiaozhi/v1/',{'Origin':'https://untrusted.invalid'}),('/xiaozhi/v1/?token=invalid',{})):
            with self.assertRaises(WebSocketDisconnect):
                with self.client.websocket_connect(path,headers={**headers,**extra}):pass
        self.assertEqual(self.client.post('/xiaozhi/ota/',headers={**headers,'Authorization':'Bearer invalid'}).status_code,403)
        ws,_=self.open(headers)
        with self.assertRaises(WebSocketDisconnect):
            with self.client.websocket_connect('/xiaozhi/v1/',headers=headers):pass

    def test_pipeline_failure_then_next_turn_recovers(self):
        ws,_=self.open(self.register());self.speech.fail=True
        ws.send_json({'type':'listen','state':'detect','text':'Test failure'})
        events,frames=self.receive_turn(ws)
        self.assertFalse(frames);self.assertEqual(events[-2]['code'],'pipeline_failed')
        self.assertNotIn('private detail',json.dumps(events))
        self.speech.fail=False;ws.send_json({'type':'listen','state':'detect','text':'Test recovery'})
        _,frames=self.receive_turn(ws);self.assertEqual(len(frames),2)

    def test_failed_mcp_initialization_reaps_its_owned_subprocess(self):
        async def check():
            mcp=MCPClient(self.settings)
            with patch.object(mcp,'request',new=AsyncMock(side_effect=asyncio.TimeoutError)):
                with self.assertRaises(asyncio.TimeoutError):await mcp.__aenter__()
            self.assertIsNotNone(mcp.process.returncode)
            self.assertTrue(mcp.process.stdin.is_closing())
        asyncio.run(check())

    def test_whole_turn_timeout_reported_and_connection_recovers(self):
        self.settings.provider_timeout=-139.95  # 50 ms total budget, test-only
        ws,_=self.open(self.register());self.speech.delay=10
        ws.send_json({'type':'listen','state':'detect','text':'Timeout fixture'})
        events,frames=self.receive_turn(ws);self.assertFalse(frames)
        self.assertEqual(events[-2]['code'],'turn_timeout')
        self.settings.provider_timeout=90;self.speech.delay=0
        ws.send_json({'type':'listen','state':'detect','text':'Recovery fixture'})
        self.assertEqual(len(self.receive_turn(ws)[1]),2)

    def test_wrong_session_and_malformed_json_close_then_reconnect(self):
        headers=self.register()
        for payload in ([],{'type':'abort','session_id':'another-session'},{'type':'mcp','payload':[]},{'type':'listen','state':'detect','text':{}}):
            with self.client.websocket_connect('/xiaozhi/v1/',headers=headers) as ws:
                ws.send_json({**self.hello(),'features':{}});ws.receive_json();ws.send_json(payload)
                with self.assertRaises(WebSocketDisconnect):ws.receive_json()
        ws,_=self.open(headers);ws.send_json({'type':'abort'});self.assertEqual(ws.receive_json()['state'],'stop')

    def test_malformed_hello_and_corrupt_opus_do_not_leak_server_errors(self):
        headers=self.register()
        for hello in ([],{**self.hello(),'audio_params':[1]},{**self.hello(),'features':[1]}):
            with self.client.websocket_connect('/xiaozhi/v1/',headers=headers) as ws:
                ws.send_json(hello)
                with self.assertRaises(WebSocketDisconnect):ws.receive_json()
        ws,_=self.open(headers);ws.send_json({'type':'listen','state':'start','mode':'manual'});ws.send_bytes(b'\xff'*4096)
        with self.assertRaises(WebSocketDisconnect):ws.receive_json()
        with closing(sqlite3.connect(self.settings.db)) as db:self.assertEqual(db.execute('SELECT COUNT(*) FROM turns').fetchone()[0],0)
