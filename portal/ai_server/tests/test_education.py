import asyncio
import json
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import httpx
from ai_server.providers import Providers,ProviderError
from ai_server.context import prepare_context
from ai_server.settings import Settings
from ai_server.tests.test_service import ServiceFixture

RealClient=httpx.AsyncClient


class EducationTests(TestCase):
    def call(self,chunks,question='Translate apple into Vietnamese.'):
        async def check():
            seen=[]
            def handle(request):
                seen.append(json.loads(request.content))
                return httpx.Response(200,content='\n'.join(json.dumps(c) for c in chunks),headers={'Content-Type':'application/x-ndjson'})
            transport=httpx.MockTransport(handle)
            def client(**kwargs):return RealClient(transport=transport,**kwargs)
            messages=[{'role':'system','content':'Teacher fixture'},{'role':'user','content':question}]
            provider=Providers(Settings(tokenizer=''))
            try:
                with patch('ai_server.providers.httpx.AsyncClient',client):result=await provider.llm(messages,'fixture-model')
                self.assertEqual(messages[0]['content'],'Teacher fixture')
                return result,seen[0]
            finally:provider.cpu.shutdown(wait=True)
        return asyncio.run(check())

    def test_stream_reassembles_json_and_fixes_translation_instruction(self):
        result,body=self.call([{'message':{'content':'{"rep'}},{'message':{'content':'ly":"quả táo"}'}},{'done':True,'done_reason':'stop','eval_count':5}])
        self.assertEqual(result['content'],'quả táo');self.assertTrue(body['stream'])
        self.assertNotIn('do not translate',body['messages'][0]['content'])
        self.assertTrue(result['metrics']['streamed_validated_before_tts'])

    def test_incomplete_invalid_or_truncated_stream_never_produces_speech(self):
        variants=[
            [{'message':{'content':'{"reply":"unfinished'} }],
            [{'message':{'content':'{"reply":"partial"}'}},{'done':True,'done_reason':'length'}],
            [{'message':{'content':'<think>private reasoning'}},{'done':True,'done_reason':'stop'}],
            [{'message':{'content':'[]'}},{'done':True,'done_reason':'stop'}],
            [{'message':{'content':'{"reply":null}'}},{'done':True,'done_reason':'stop'}],
            [['invalid stream object']],
        ]
        for chunks in variants:
            with self.subTest(chunks=chunks),self.assertRaises(ProviderError):self.call(chunks)

    def test_exact_question_echo_is_rejected_without_canned_answer(self):
        with self.assertRaises(ProviderError):self.call([{'message':{'content':'{"reply":"WeWIN có dạy IELTS không?"}'}},{'done':True,'done_reason':'stop'}],'WeWIN có dạy IELTS không?')

    def test_context_removes_only_old_complete_pairs(self):
        messages=[{'role':'system','content':'Policy'}]
        for i in range(5):messages += [{'role':'user','content':'old '*40},{'role':'assistant','content':'old reply '*40}]
        messages += [{'role':'user','content':'Current question'},{'role':'tool','content':'Required current facts'}]
        kept,meta=prepare_context(messages,'fixture','',limit=1500)
        self.assertGreater(meta['history_pairs_removed'],0)
        self.assertEqual(kept[0],messages[0]);self.assertEqual(kept[-2:],messages[-2:])
        self.assertLessEqual(meta['input_budget_estimate'],1500)
        self.assertEqual(len(messages),13)

    def test_oversized_current_tool_or_prompt_fails_without_silent_truncation(self):
        with self.assertRaises(ValueError):prepare_context([{'role':'system','content':'Policy'},{'role':'user','content':'Current'},{'role':'tool','content':'x'*5000}],'fixture','',limit=1500)


class RuntimeTests(ServiceFixture):
    def test_runtime_details_are_admin_only_and_build_is_a_startup_snapshot(self):
        self.assertEqual(self.client.get('/v1/runtime').status_code,401)
        info=self.client.get('/v1/runtime',headers=self.headers).json()
        self.assertEqual(info['database'],str(self.settings.db.resolve()))
        self.assertNotIn(self.settings.admin_key(),json.dumps(info))
        original=self.client.get('/health').json()['build']
        with patch('ai_server.runtime.source_fingerprint',return_value='changed-on-disk'):
            self.assertEqual(self.client.get('/health').json()['build'],original)
