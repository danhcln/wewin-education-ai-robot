"""Portal integration with a simulated management transport, no physical device."""
import json
from unittest import TestCase
from unittest.mock import patch
import httpx
from fastapi import HTTPException
import test_portal
from backend import db
from backend.self_hosted import SelfHostedAdapter
from ai_server.store import digest


class SelfHostedTests(TestCase):
    setUp=test_portal.PortalTests.setUp
    call=test_portal.PortalTests.call
    user=test_portal.PortalTests.user
    as_user=test_portal.PortalTests.as_user

    def prepare(self):
        rid=self.call('GET','/robots')['items'][0]['id']
        self.call('POST',f'/robots/{rid}/self-hosted',{'confirmed':True})
        return rid

    def remote(self,method,path,body=None,allow_missing=False):
        if path=='/v1/catalog':return {'models':[{'id':'test-model','name':'TEST MODEL'}],'voices':[{'id':'F1','name':'TEST VOICE'}],'languages':[{'id':'vi-VN','name':'vi'}],'asr_model_configured':True}
        if method=='PUT':
            if body['expected_revision']!=(self.observed['revision'] if self.observed else 0):raise HTTPException(409,'revision conflict')
            self.observed={'config':body['config'],'revision':body['expected_revision']+1,'config_hash':digest(body['config']),'loaded':True}
            self.writes+=1
        return self.observed

    def fake(self):
        self.observed=None;self.writes=0
        mock=patch.object(SelfHostedAdapter,'request',side_effect=self.remote)
        mock.start();self.addCleanup(mock.stop)

    def candidate(self,rid):
        return self.call('POST',f'/robots/{rid}/roles/builtin-english-teacher/candidate',{'version':0,'role_version':1},201)

    def test_link_requires_admin_confirmation_and_preserves_desired(self):
        self.fake()
        rid=self.call('GET','/robots')['items'][0]['id']
        self.call('POST',f'/robots/{rid}/self-hosted',{'confirmed':False},422)
        self.user();c,h=self.as_user('student')
        self.call('POST',f'/robots/{rid}/self-hosted',{'confirmed':True},403,c,h)
        self.prepare()
        self.assertEqual(self.call('GET',f'/robots/{rid}/config')['version'],0)

    def test_role_candidate_apply_and_runtime_readback(self):
        self.fake();rid=self.prepare();c=self.candidate(rid)
        self.assertEqual(c['config']['ai_model'],'test-model');self.assertEqual(c['config']['voice'],'F1')
        self.assertEqual(self.writes,0)
        result=self.call('POST',f'/robots/{rid}/config/apply',{'candidate_id':c['id'],'confirmed':True})
        self.assertEqual(result['sync_state'],'server_applied_verified');self.assertFalse(result['robot_applied']);self.assertEqual(self.writes,1)
        self.assertEqual(self.observed['config']['system_prompt'],c['config']['system_prompt'])
        status=self.call('GET',f'/robots/{rid}/config/sync-status');self.assertTrue(status['server_applied'])
        uid=self.user();self.call('POST','/device-bindings',{'user_id':uid,'device_id':rid});client,headers=self.as_user('student')
        observed=self.call('GET',f'/robots/{rid}/config/sync-status',client=client,headers=headers)
        self.assertEqual(observed['observed']['system_prompt'],'')
        self.call('GET',f'/robots/{rid}/self-hosted',expected=403,client=client,headers=headers)
        self.call('POST',f'/robots/{rid}/config/apply',{'candidate_id':c['id'],'confirmed':True},409)

    def test_mismatched_readback_never_commits_desired_or_verified(self):
        self.fake();rid=self.prepare();c=self.candidate(rid)
        original=self.remote
        def tamper(method,path,body=None,allow_missing=False):
            result=original(method,path,body,allow_missing)
            if result and path!='/v1/catalog' and method=='GET':return {**result,'config_hash':'wrong-hash'}
            return result
        with patch.object(SelfHostedAdapter,'request',side_effect=tamper):
            self.call('POST',f'/robots/{rid}/config/apply',{'candidate_id':c['id'],'confirmed':True},502)
        self.assertEqual(self.call('GET',f'/robots/{rid}/config')['version'],0)
        with db.connection() as conn:self.assertEqual(conn.execute('SELECT state FROM self_hosted_jobs').fetchone()[0],'apply_failed')

    def test_relink_invalidates_candidate_before_server_write(self):
        self.fake();rid=self.prepare();c=self.candidate(rid)
        self.call('POST',f'/robots/{rid}/self-hosted',{'confirmed':True})
        self.call('POST',f'/robots/{rid}/config/apply',{'candidate_id':c['id'],'confirmed':True},409)
        self.assertEqual(self.writes,0)

    def test_external_revision_conflict_and_failure_do_not_overwrite_local(self):
        self.fake();rid=self.prepare();c=self.candidate(rid)
        self.observed={'revision':4}
        self.call('POST',f'/robots/{rid}/config/apply',{'candidate_id':c['id'],'confirmed':True},409)
        self.assertEqual(self.call('GET',f'/robots/{rid}/config')['version'],0)
        with patch.object(SelfHostedAdapter,'apply',side_effect=HTTPException(504,'timeout')):
            self.call('POST',f'/robots/{rid}/config/apply',{'candidate_id':c['id'],'confirmed':True},504)
        with db.connection() as conn:self.assertEqual(conn.execute('SELECT state FROM self_hosted_jobs').fetchone()[0],'apply_failed')

    def test_newer_local_config_during_remote_apply_is_preserved(self):
        self.fake();rid=self.prepare();c=self.candidate(rid);original=self.remote
        def concurrent(method,path,body=None,allow_missing=False):
            result=original(method,path,body,allow_missing)
            if method=='PUT':self.call('PUT',f'/robots/{rid}/config',{'version':0,'greeting':'newer local edit'})
            return result
        with patch.object(SelfHostedAdapter,'request',side_effect=concurrent):
            self.call('POST',f'/robots/{rid}/config/apply',{'candidate_id':c['id'],'confirmed':True},409)
        self.assertEqual(self.call('GET',f'/robots/{rid}/config')['config']['greeting'],'newer local edit')

    def test_last_verified_job_is_not_current_proof_when_readback_fails_or_changes(self):
        self.fake();rid=self.prepare();c=self.candidate(rid)
        self.call('POST',f'/robots/{rid}/config/apply',{'candidate_id':c['id'],'confirmed':True})
        with patch.object(SelfHostedAdapter,'request',side_effect=HTTPException(504,'fixture timeout')):
            status=self.call('GET',f'/robots/{rid}/config/sync-status')
        self.assertFalse(status['server_applied']);self.assertEqual(status['cloud_state'],'unavailable');self.assertIsNone(status['observed'])
        self.observed['revision']=9
        status=self.call('GET',f'/robots/{rid}/config/sync-status')
        self.assertFalse(status['server_applied']);self.assertEqual(status['state'],'out_of_sync')

    def test_http_auth_timeout_and_secret_masking(self):
        path=db.DB.parent/'ai-key';path.write_text('test-only-management-secret-long-enough',encoding='utf-8')
        adapter=SelfHostedAdapter({'agent_id':'test'})
        with patch.dict('os.environ',{'WEWIN_AI_ADMIN_KEY_FILE':str(path)}),patch('backend.self_hosted.httpx.Client') as client:
            connection=client.return_value.__enter__.return_value
            connection.request.side_effect=httpx.ReadTimeout('private-provider-detail')
            with self.assertRaises(HTTPException) as error:adapter.request('GET','/v1/catalog')
            self.assertEqual(error.exception.status_code,504);self.assertNotIn('private-provider-detail',str(error.exception.detail))
            connection.request.side_effect=None;connection.request.return_value=httpx.Response(403)
            with self.assertRaises(HTTPException) as error:adapter.request('GET','/v1/catalog')
            self.assertEqual(error.exception.status_code,502)
