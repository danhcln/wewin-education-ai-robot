"""Real HTTP/persistence tests of the local workflow; no test claims Cloud success."""
import json
import os
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import test_portal
from backend import db
from backend.ai_migrations import migrate_ai
from backend.relationships import migrate_relationships
from backend.curriculum import migrate_curriculum


class RobotAIWorkflowTests(TestCase):
    setUp=test_portal.PortalTests.setUp
    call=test_portal.PortalTests.call
    user=test_portal.PortalTests.user
    as_user=test_portal.PortalTests.as_user

    def robot(self):
        rows=self.call('GET','/robots')['items'];self.assertTrue(rows)
        return rows[0]['id']

    def config(self,rid):
        return self.call('GET','/robots/'+rid+'/config')

    def role(self):
        body={'title':'WeWIN Robot Tutor','system_prompt':'Explain one step at a time.','greeting':'Win sẵn sàng học cùng bạn!','description':'An educational tutor','language':'en','voice_preference':'requested-voice-not-verified','avatar':'stem','status':'active','lesson_id':'builtin-hello','version':1}
        result=self.call('POST','/roles',body,201)
        return result['id'],body

    def role_candidate(self,rid,role_id,role_version=1,version=0):
        return self.call('POST',f'/robots/{rid}/roles/{role_id}/candidate',{'version':version,'role_version':role_version},201)

    def test_role_copy_confirmation_bindings_and_replay(self):
        rid=self.robot();role_id,body=self.role();candidate=self.role_candidate(rid,role_id)
        self.assertEqual(self.config(rid)['version'],0)
        self.assertEqual(candidate['config']['system_prompt'],body['system_prompt'])
        self.assertEqual(candidate['config']['greeting'],body['greeting'])
        self.assertEqual(candidate['config']['lesson_id'],'builtin-hello')
        uri=f'/robots/{rid}/roles/{role_id}/apply'
        self.call('POST',uri,{'candidate_id':candidate['id'],'confirmed':False},422)
        saved=self.call('POST',uri,{'candidate_id':candidate['id'],'confirmed':True})
        self.assertEqual(saved['sync_state'],'saved_backend_only');self.assertFalse(saved['cloud_applied']);self.assertFalse(saved['robot_applied'])
        actual=self.config(rid);self.assertEqual(actual['config']['ai_role'],role_id);self.assertEqual(actual['config']['role_version'],1)
        self.call('PUT',f'/robots/{rid}/config',{**actual['config'],'version':1,'role_version':999},422)
        self.call('POST',uri,{'candidate_id':candidate['id'],'confirmed':True},409)
        with db.connection() as conn:
            binding=conn.execute('SELECT * FROM device_role_bindings WHERE robot_id=?',(rid,)).fetchone()
            self.assertEqual(binding['role_id'],role_id);self.assertEqual(binding['config_version'],1)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM config_history').fetchone()[0],1)
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])

    def test_builtin_roles_have_eight_distinct_avatars_and_complete_metadata(self):
        items=[r for r in self.call('GET','/roles')['items'] if r['id'].startswith('builtin-')]
        self.assertEqual(len(items),8);self.assertEqual(len({r['avatar'] for r in items}),8)
        self.assertIn('WeWIN Education Consultant',[r['display_name'] for r in items])
        for row in items:
            self.assertTrue(row['greeting']);self.assertIn('voice_preference',row);self.assertEqual(row['version'],1)

    def test_role_versions_prompt_permissions_and_conflicts(self):
        rid,body=self.role()
        updated=self.call('PUT','/roles/'+rid,{**body,'greeting':'Greeting v2'})
        self.assertEqual(updated['version'],2)
        self.call('PUT','/roles/'+rid,body,409)
        history=self.call('GET','/roles/'+rid+'/history')['items'];self.assertEqual([h['version'] for h in history],[2,1])
        self.user();c,h=self.as_user('student')
        student_role=self.call('GET','/roles/'+rid,client=c,headers=h)
        self.assertNotIn('system_prompt',student_role);self.assertFalse(student_role['can_edit'])
        self.assertTrue(all('system_prompt' not in r for r in self.call('GET','/roles',client=c,headers=h)['items']))
        self.call('GET','/roles/'+rid+'/history',expected=403,client=c,headers=h)
        self.user('teacher','teacher');t,th=self.as_user('teacher')
        self.call('PUT','/roles/'+rid,{**body,'version':2},403,t,th)

    def test_stale_candidate_and_role_version_never_overwrite(self):
        rid=self.robot();role_id,body=self.role();candidate=self.role_candidate(rid,role_id)
        self.call('PUT','/roles/'+role_id,{**body,'system_prompt':'Newer role content'})
        self.call('POST',f'/robots/{rid}/roles/{role_id}/apply',{'candidate_id':candidate['id'],'confirmed':True},409)
        self.assertEqual(self.config(rid)['version'],0)
        candidate=self.role_candidate(rid,role_id,role_version=2)
        config=self.config(rid)
        self.call('PUT',f'/robots/{rid}/config',{**config['config'],'version':0,'greeting':'A newer manual draft'})
        self.call('POST',f'/robots/{rid}/config/candidates/save',{'candidate_id':candidate['id'],'confirmed':True},409)
        self.assertEqual(self.config(rid)['config']['greeting'],'A newer manual draft')

    def test_candidate_expiry_creator_scope_and_robot_permissions(self):
        rid=self.robot();role_id,_=self.role();candidate=self.role_candidate(rid,role_id)
        with db.connection() as conn:conn.execute('UPDATE config_candidates SET expires_at=0 WHERE id=?',(candidate['id'],))
        self.call('POST',f'/robots/{rid}/config/candidates/save',{'candidate_id':candidate['id'],'confirmed':True},410)
        teacher=self.user('teacher','teacher');self.call('POST','/device-bindings',{'user_id':teacher,'device_id':rid});c,h=self.as_user('teacher')
        tc=self.call('POST',f'/robots/{rid}/roles/{role_id}/candidate',{'version':0,'role_version':1},201,c,h)
        self.call('POST',f'/robots/{rid}/config/candidates/save',{'candidate_id':tc['id'],'confirmed':True},403)
        self.user();student,sh=self.as_user('student')
        self.call('POST',f'/robots/{rid}/roles/{role_id}/candidate',{'version':0,'role_version':1},403,student,sh)
        self.call('GET',f'/robots/{rid}/config',expected=403,client=student,headers=sh)

    def test_cloud_apply_and_read_are_explicitly_blocked_and_audited(self):
        rid=self.robot();role_id,_=self.role();candidate=self.role_candidate(rid,role_id)
        for _ in range(5):
            error=self.call('POST',f'/robots/{rid}/config/apply',{'candidate_id':candidate['id'],'confirmed':True},409)
            self.assertEqual(error['detail']['state'],'unsupported')
        self.call('POST',f'/robots/{rid}/config/apply',{'candidate_id':candidate['id'],'confirmed':True},429)
        self.call('POST',f'/robots/{rid}/config/read-cloud',expected=409)
        status=self.call('GET',f'/robots/{rid}/config/sync-status')
        self.assertIsNone(status['observed']);self.assertFalse(status['cloud_applied']);self.assertFalse(status['capabilities']['apply_supported'])
        self.assertEqual(self.config(rid)['version'],0)
        with db.connection() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit WHERE action='cloud_apply_unsupported'").fetchone()[0],5)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM config_history').fetchone()[0],0)

    def test_student_prompt_redaction_and_apply_denial(self):
        rid=self.robot();role_id,_=self.role();candidate=self.role_candidate(rid,role_id)
        uid=self.user();self.call('POST','/device-bindings',{'user_id':uid,'device_id':rid});c,h=self.as_user('student')
        detail=self.call('GET',f'/robots/{rid}/config',client=c,headers=h)
        self.assertTrue(detail['prompt_redacted']);self.assertEqual(detail['config']['system_prompt'],'')
        self.call('POST',f'/robots/{rid}/config/apply',{'candidate_id':candidate['id'],'confirmed':True},403,c,h)
        self.call('POST',f'/robots/{rid}/roles/{role_id}/apply',{'candidate_id':candidate['id'],'confirmed':True},403,c,h)
        self.call('GET',f'/robots/{rid}/history/1',expected=403,client=c,headers=h)
        with db.connection() as conn:self.assertEqual(conn.execute("SELECT COUNT(*) FROM audit WHERE action='cloud_apply_denied'").fetchone()[0],1)

    def test_config_restore_creates_new_version_and_preserves_history(self):
        rid=self.robot();data=self.config(rid)
        self.call('PUT',f'/robots/{rid}/config',{**data['config'],'version':0,'greeting':'First saved greeting'})
        self.call('PUT',f'/robots/{rid}/config',{**data['config'],'version':1,'greeting':'Second saved greeting'})
        self.call('POST',f'/robots/{rid}/config/restore',{'version':2,'target_version':1,'confirmed':False},422)
        restored=self.call('POST',f'/robots/{rid}/config/restore',{'version':2,'target_version':1,'confirmed':True})
        self.assertEqual(restored['version'],3);self.assertEqual(restored['sync_state'],'saved_backend_only')
        self.assertEqual(self.config(rid)['config']['greeting'],'First saved greeting')
        self.assertEqual(len(self.call('GET',f'/robots/{rid}/history')['items']),3)
        self.call('POST',f'/robots/{rid}/config/restore',{'version':2,'target_version':1,'confirmed':True},409)

    def test_manual_config_candidate_and_catalog_truth(self):
        rid=self.robot();config=self.config(rid)
        candidate=self.call('POST',f'/robots/{rid}/config/candidates',{**config['config'],'version':0,'assistant_name':'Win Candidate'},201)
        self.assertEqual(candidate['capabilities']['models'],[]);self.assertEqual(candidate['capabilities']['voices'],[]);self.assertEqual(candidate['capabilities']['languages'],[])
        self.assertFalse(candidate['capabilities']['catalog_verified'])
        saved=self.call('POST',f'/robots/{rid}/config/candidates/save',{'candidate_id':candidate['id'],'confirmed':True})
        self.assertEqual(saved['version'],1)
        self.assertEqual(self.config(rid)['config']['assistant_name'],'Win Candidate')

    def test_official_connection_request_cannot_unlock_apply_or_disclose_secret(self):
        rid=self.robot();profile={'version':0,'provider':'XiaoZhi — requested, unverified','agent_reference':'unverified-agent','origin':'https://xiaozhi.me','documentation_url':'https://xiaozhi.me/xz-docs','credential_env':'WEWIN_CLOUD_MANAGEMENT_TOKEN'}
        result=self.call('PUT',f'/robots/{rid}/cloud-connection',profile)
        self.assertEqual(result['state'],'verification_pending')
        with patch.dict(os.environ,{'WEWIN_CLOUD_MANAGEMENT_TOKEN':'test-only-not-a-real-cloud-credential'}):
            connection=self.call('GET',f'/robots/{rid}/cloud-connection')
            self.assertTrue(connection['capabilities']['credential_configured']);self.assertFalse(connection['capabilities']['apply_supported'])
            self.assertNotIn('test-only-not-a-real-cloud-credential',json.dumps(connection))
        self.call('PUT',f'/robots/{rid}/cloud-connection',profile,409)
        self.call('PUT',f'/robots/{rid}/cloud-connection',{**profile,'version':1,'origin':'https://xiaozhi.me/api/internal'},422)
        self.call('PUT',f'/robots/{rid}/cloud-connection',{**profile,'version':1,'documentation_url':'https://xiaozhi.me/?token=hidden'},422)

    def test_v5_migration_preserves_existing_roles_config_and_idempotence(self):
        path=Path(self.folder.name)/'pre-ai.sqlite3'
        with patch.object(db,'DB',path):
            db.migrate();migrate_relationships();migrate_curriculum()
            original={'title':'Original role','system_prompt':'Keep the original prompt','status':'draft'}
            with db.connection() as conn:
                conn.execute('INSERT INTO ai_roles(id,owner_id,title,payload,status,created_at,updated_at) VALUES(?,?,?,?,?,?,?)',('existing','local-admin','Original role',json.dumps(original),'draft',123,123))
                conn.execute("INSERT INTO robot_config VALUES('old-robot',7,'{}','saved_backend_only',123,'local-admin')")
            migrate_ai();migrate_ai()
            with db.connection() as conn:
                self.assertEqual(conn.execute('SELECT MAX(version) FROM schema_version').fetchone()[0],5)
                self.assertEqual(conn.execute("SELECT version FROM robot_config WHERE robot_id='old-robot'").fetchone()[0],7)
                self.assertEqual(json.loads(conn.execute("SELECT payload FROM role_versions WHERE role_id='existing'").fetchone()[0])['system_prompt'],original['system_prompt'])
                self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')
