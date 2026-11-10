"""HTTP tests use an isolated temporary Portal DB, never the demo or Portal runtime DB."""
import os
import tempfile
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
from io import BytesIO
from PIL import Image
from fastapi.testclient import TestClient
from backend.app import app
from backend import db, auth, integrations, robots

ORIGIN='http://127.0.0.1:8001'
TOKEN='wewin-test-token-never-a-real-secret-12345'

class PortalTests(TestCase):
    def setUp(self):
        self.folder=tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.patches=[patch.object(db,'DB',Path(self.folder.name)/'test.sqlite3'),patch.object(integrations.settings,'ADMIN_SYNC_TOKEN',TOKEN)]
        for p in self.patches:
            p.start();self.addCleanup(p.stop)
        auth.attempts.clear()
        self.client=TestClient(app,base_url=ORIGIN)
        self.client.__enter__();self.addCleanup(self.client.__exit__,None,None,None)
        self.headers={'Origin':ORIGIN}
        r=self.client.post('/api/portal/login',headers={**self.headers,'Authorization':'Bearer '+TOKEN})
        self.assertEqual(r.status_code,200,r.text)
        self.headers['X-WeWIN-CSRF']=r.json()['csrf']

    def call(self,method,path,body=None,expected=200,client=None,headers=None,**kwargs):
        c=client or self.client
        r=c.request(method,'/api/portal'+path,json=body,headers=headers or self.headers,**kwargs)
        self.assertEqual(r.status_code,expected,r.text)
        return r.json()

    def user(self,name='student',role='student'):
        return self.call('POST','/users',{'username':name,'display_name':name,'role':role,'password':'Test-password-12345'},201)['id']

    def as_user(self,name):
        c=TestClient(app,base_url=ORIGIN)
        r=c.post('/api/portal/auth/login',json={'username':name,'password':'Test-password-12345'},headers={'Origin':ORIGIN})
        self.assertEqual(r.status_code,200,r.text)
        return c,{'Origin':ORIGIN,'X-WeWIN-CSRF':r.json()['csrf']}

    def lesson(self,status='published'):
        return self.call('POST','/lessons',{'title':'Unit Test Lesson','content':'Hello means xin chào.','status':status,'exercises':[{'question':'Xin chào?','answer':'Hello'}]},201)['id']

    def test_auth_csrf_origin_logout(self):
        self.call('POST','/users',{},403,headers={'Origin':'https://evil.example'})
        self.call('POST','/tasks',{'title':'blocked'},403,headers={'Origin':ORIGIN})
        self.call('GET','/session')
        self.call('POST','/logout')
        self.call('GET','/session',expected=401)
        r=self.client.post('/api/portal/login',headers={'Origin':ORIGIN,'Authorization':'Bearer invalid'})
        self.assertEqual(r.status_code,401)

    def test_password_rbac_and_student_privacy(self):
        uid=self.user();other=self.user('student2')
        c,h=self.as_user('student')
        self.call('POST','/lessons',{'title':'denied','content':'x'},403,c,h)
        self.call('GET','/users',expected=403,client=c,headers=h)
        self.call('GET','/learning/dashboard?user_id='+other,expected=403,client=c,headers=h)
        self.assertEqual(self.call('GET','/session',client=c,headers=h)['user_id'],uid)
        self.call('PUT','/profile',{'display_name':'Learner','level':'A1','goal':'Practice greetings'},client=c,headers=h)
        self.assertEqual(self.call('GET','/profile',client=c,headers=h)['level'],'A1')
        self.call('POST','/users',{'username':'student','display_name':'x','role':'student','password':'Test-password-12345'},409)
        self.call('POST','/users',{'username':'short','display_name':'x','role':'student','password':'bad'},422)

    def test_lesson_practice_scoring_and_persistence(self):
        lid=self.lesson();self.call('GET','/lessons/'+lid)
        sid=self.call('POST','/learning/sessions',{'lesson_id':lid},201)['id']
        same=self.call('POST','/learning/sessions',{'lesson_id':lid},201)['id'];self.assertEqual(sid,same)
        self.call('POST','/learning/sessions/'+sid+'/complete',{'answers':[]},422)
        result=self.call('POST','/learning/sessions/'+sid+'/complete',{'answers':[' hello ']})
        self.assertEqual(result['score'],100)
        self.call('POST','/learning/sessions/'+sid+'/complete',{'answers':['Hello']},409)
        d=self.call('GET','/learning/dashboard');self.assertEqual(d['total_sessions'],1);self.assertEqual(d['completed_lessons'],1)
        with db.connection() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM learning_progress').fetchone()[0],1)
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])
        db.migrate();self.assertEqual(self.call('GET','/learning/dashboard')['total_sessions'],1)

    def test_draft_owner_and_cross_user_completion(self):
        draft=self.lesson('draft');uid=self.user();c,h=self.as_user('student')
        self.call('GET','/lessons/'+draft,expected=403,client=c,headers=h)
        self.call('POST','/learning/sessions',{'lesson_id':draft},422)
        lid=self.lesson();sid=self.call('POST','/learning/sessions',{'lesson_id':lid},201)['id']
        self.call('POST','/learning/sessions/'+sid+'/complete',{'answers':['Hello']},403,c,h)

    def test_config_versions_and_truthful_capabilities(self):
        data=self.call('GET','/overview');self.assertEqual(data['cloud_config_sync'],'unsupported')
        if not data['robots']:
            self.skipTest('No real registry robots on this machine')
        rid=data['robots'][0]['id'];first=self.call('GET','/robots/'+rid+'/config')
        body={**first['config'],'version':first['version'],'assistant_name':'Win'}
        saved=self.call('PUT','/robots/'+rid+'/config',body);self.assertEqual(saved['sync_state'],'saved_backend_only')
        self.call('PUT','/robots/'+rid+'/config',body,409)
        self.call('PUT','/robots/'+rid+'/config',{**body,'speech_rate':8},422)
        self.call('PUT','/robots/'+rid+'/config',{**body,'version':saved['version'],'lesson_id':'nonexistent'},422)
        self.assertFalse(first['wake_word']['apply_supported']);self.assertFalse(first['bluetooth']['scan_supported'])
        self.assertEqual(len(self.call('GET','/robots/'+rid+'/history')['items']),1)
        uid=self.user();c,h=self.as_user('student')
        self.call('GET','/robots/'+rid+'/config',expected=403,client=c,headers=h)
        self.call('POST','/device-bindings',{'user_id':uid,'device_id':rid})
        self.call('GET','/robots/'+rid+'/config',client=c,headers=h)
        self.call('PUT','/robots/'+rid+'/config',{**body,'version':saved['version']},403,c,h)

    def test_roles_and_paths_enrollment(self):
        rid=self.call('POST','/roles',{'title':'Coach','system_prompt':'Help learners','status':'active'},201)['id']
        self.call('PUT','/roles/'+rid,{'title':'Coach','system_prompt':'Help learners','status':'archived'})
        lid=self.lesson();pid=self.call('POST','/paths',{'title':'Path','lesson_ids':[lid]},201)['id']
        self.call('POST','/paths',{'title':'Bad','lesson_ids':[lid,lid]},422)
        uid=self.user();self.call('POST','/paths/'+pid+'/enroll',{'user_id':uid})
        c,h=self.as_user('student');self.assertEqual(len(self.call('GET','/paths',client=c,headers=h)['items']),1)
        self.call('PUT','/paths/'+pid,{'title':'Revised','lesson_ids':[lid]})

    def test_memory_consent_secret_rejection_and_privacy(self):
        self.call('POST','/memories',{'title':'Goal','content':'Learn English','consent':False},422)
        self.call('POST','/memories',{'title':'Goal','content':'password: secret-value','consent':True},422)
        mid=self.call('POST','/memories',{'title':'Goal','content':'Learn English','consent':True},201)['id']
        self.user();c,h=self.as_user('student')
        self.assertEqual(self.call('GET','/memories',client=c,headers=h)['items'],[])
        self.call('DELETE','/memories/'+mid,expected=403,client=c,headers=h)
        self.call('PUT','/memories/'+mid,{'title':'Goal','content':'Learn more','category':'vocabulary','consent':True})
        self.call('DELETE','/memories/'+mid)

    def test_task_assignment_history_and_completion(self):
        uid=self.user();lid=self.lesson()
        tid=self.call('POST','/tasks',{'title':'Practice','student_id':uid,'lesson_id':lid,'due_date':'2026-11-08'},201)['id']
        self.call('PUT','/tasks/'+tid,{'title':'Practice daily','student_id':uid,'priority':'high'})
        c,h=self.as_user('student');self.call('POST','/tasks/'+tid+'/complete',client=c,headers=h)
        self.assertEqual(len(self.call('GET','/tasks/'+tid+'/history')['items']),3)
        self.call('DELETE','/tasks/'+tid,expected=403,client=c,headers=h)
        self.call('DELETE','/tasks/'+tid)
        self.call('POST','/tasks',{'title':'Bad','due_date':'no-date'},422)

    def test_knowledge_fts_upload_reindex_and_access(self):
        kid=self.call('POST','/knowledge',{'title':'Vocabulary','content':'Từ vựng Cambridge rainforest'},201)['id']
        self.assertEqual(len(self.call('GET','/knowledge?q=rainforest')['items']),1)
        self.call('POST','/knowledge/'+kid+'/reindex')
        r=self.client.post('/api/portal/knowledge/upload',files={'file':('notes.txt',b'English literacy','text/plain')},headers=self.headers)
        self.assertEqual(r.status_code,201,r.text)
        r=self.client.post('/api/portal/knowledge/upload',files={'file':('bad.pdf',b'bad','application/pdf')},headers=self.headers)
        self.assertEqual(r.status_code,415)
        self.user();c,h=self.as_user('student')
        self.assertEqual(self.call('GET','/knowledge?q=rainforest',client=c,headers=h)['items'],[])
        self.call('DELETE','/knowledge/'+kid)
        self.assertEqual(self.call('GET','/knowledge?q=rainforest')['items'],[])

    def test_media_validation_binding_and_providers(self):
        self.call('POST','/media',{'title':'Bad','kind':'audio_asset','url':'javascript:alert(1)'},422)
        mid=self.call('POST','/media',{'title':'Clip','kind':'video_reference','url':'https://www.youtube.com/watch?v=sample'},201)['id']
        self.call('POST','/media/'+mid+'/bind',{'lesson_id':self.lesson()})
        self.assertEqual(self.call('GET','/media')['robot_streaming'],'unsupported')
        data=BytesIO();Image.new('RGB',(20,20),'white').save(data,format='PNG')
        with patch.dict(os.environ,{'WEWIN_TESSERACT':'Z:/missing-tesseract.exe','WEWIN_AI_BASE_URL':'','WEWIN_AI_MODEL':''}):
            r=self.client.post('/api/portal/ocr',files={'file':('img.png',data.getvalue(),'image/png')},headers=self.headers);self.assertEqual(r.status_code,503,r.text)
            self.call('POST','/homework',{'question':'Explain 1+1','consent':True},503)
        self.assertEqual(self.call('GET','/homework')['items'][0]['status'],'provider_unavailable')
        r=self.client.post('/api/portal/ocr',files={'file':('bad.png',b'fake','image/png')},headers=self.headers);self.assertEqual(r.status_code,422)

    def test_docx_extraction_and_invalid_documents(self):
        import zipfile
        data=BytesIO()
        with zipfile.ZipFile(data,'w') as archive:
            archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Biology vocabulary photosynthesis</w:t></w:r></w:p></w:body></w:document>')
        r=self.client.post('/api/portal/knowledge/upload',files={'file':('notes.docx',data.getvalue(),'application/vnd.openxmlformats-officedocument.wordprocessingml.document')},headers=self.headers)
        self.assertEqual(r.status_code,201,r.text)
        self.assertEqual(len(self.call('GET','/knowledge?q=photosynthesis')['items']),1)
        for name,raw in [('bad.docx',b'not-a-zip'),('bad.txt',b'\xff\x00'),('big.txt',b'x'*(3*1024*1024+1))]:
            r=self.client.post('/api/portal/knowledge/upload',files={'file':(name,raw)},headers=self.headers)
            self.assertIn(r.status_code,(413,422),r.text)

    def test_guardian_reports_and_audit_privacy(self):
        uid=self.user();gid=self.user('guardian','guardian');self.user('other')
        self.call('POST','/guardian-links',{'guardian_id':gid,'student_id':uid})
        c,h=self.as_user('guardian')
        self.call('GET','/learning/dashboard?user_id='+uid,client=c,headers=h)
        self.call('GET','/logs',expected=403,client=c,headers=h)
        logs=self.call('GET','/logs')['items'];self.assertTrue(logs)
        self.assertNotIn(TOKEN,str(logs));self.assertNotIn('Test-password',str(logs))

    def test_teacher_scope_role_and_knowledge_bindings(self):
        uid=self.user();other=self.user('other');tid=self.user('teacher','teacher')
        c,h=self.as_user('teacher')
        self.call('GET','/learning/dashboard?user_id='+uid,expected=403,client=c,headers=h)
        self.call('POST','/teacher-students',{'teacher_id':tid,'student_id':uid})
        self.call('GET','/learning/dashboard?user_id='+uid,client=c,headers=h)
        self.call('GET','/learning/dashboard?user_id='+other,expected=403,client=c,headers=h)
        self.call('POST','/tasks',{'title':'Teacher assignment','student_id':uid},201,c,h)
        self.call('POST','/tasks',{'title':'Forbidden assignment','student_id':other},403,c,h)
        self.assertEqual(self.call('GET','/students',client=c,headers=h)['items'][0]['id'],uid)
        role='builtin-english-teacher'
        self.call('POST','/role-bindings',{'role_id':role,'user_id':uid},client=c,headers=h)
        self.call('POST','/role-bindings',{'role_id':role,'user_id':'missing-user'},422)
        kid=self.call('POST','/knowledge',{'title':'School notes','content':'Classroom English'},201)['id']
        self.call('POST','/knowledge/'+kid+'/bindings',{'role_id':role})
        self.assertEqual(len(self.call('GET','/knowledge/'+kid+'/bindings')['items']),1)
        self.call('POST','/knowledge/'+kid+'/bindings',{'role_id':role},403,c,h)
        self.assertEqual(self.call('GET','/learning/dashboard?user_id='+uid)['assigned_role']['id'],role)

    def test_additive_migration_preserves_v1_config_and_closes_backups(self):
        import sqlite3
        from backend.relationships import migrate_relationships
        from backend.curriculum import migrate_curriculum
        path=Path(self.folder.name)/'legacy.sqlite3'
        with patch.object(db,'DB',path):
            with db.connection() as conn:
                conn.execute('CREATE TABLE schema_version(version INTEGER PRIMARY KEY,applied_at INTEGER NOT NULL)')
                conn.execute('INSERT INTO schema_version VALUES(1,0)')
                conn.execute('CREATE TABLE sessions(token_hash TEXT PRIMARY KEY,csrf TEXT NOT NULL,expires INTEGER NOT NULL,role TEXT NOT NULL)')
                conn.execute('CREATE TABLE robot_config(robot_id TEXT PRIMARY KEY,version INTEGER NOT NULL,payload TEXT NOT NULL,sync_state TEXT NOT NULL,updated_at INTEGER NOT NULL,updated_by TEXT NOT NULL)')
                conn.execute('CREATE TABLE config_history(robot_id TEXT NOT NULL,version INTEGER NOT NULL,payload TEXT NOT NULL,sync_state TEXT NOT NULL,updated_at INTEGER NOT NULL,updated_by TEXT NOT NULL,PRIMARY KEY(robot_id,version))')
                conn.execute('CREATE TABLE audit(id INTEGER PRIMARY KEY AUTOINCREMENT,action TEXT NOT NULL,robot_id TEXT,version INTEGER,at INTEGER NOT NULL,actor TEXT NOT NULL)')
                conn.execute("INSERT INTO robot_config VALUES('preserved',9,'{}','saved_backend_only',123,'local-admin')")
            db.migrate();migrate_relationships();migrate_curriculum();db.migrate();migrate_relationships();migrate_curriculum()
            with db.connection() as conn:
                self.assertEqual(conn.execute("SELECT version FROM robot_config WHERE robot_id='preserved'").fetchone()[0],9)
                self.assertEqual(conn.execute('SELECT MAX(version) FROM schema_version').fetchone()[0],4)
                self.assertEqual(conn.execute('PRAGMA integrity_check').fetchone()[0],'ok')
            backups=list(path.parent.glob('education-before-v*.sqlite3'))
            self.assertTrue(backups)
            for file in backups:
                moved=file.with_suffix('.verified.sqlite3');file.rename(moved);moved.rename(file)

    def test_curriculum_modules_enrollment_score_rule_and_snapshot(self):
        first=self.lesson();second=self.lesson()
        body={'title':'English course','minimum_score':80,'status':'published','modules':[{'title':'Greetings','lesson_ids':[first]},{'title':'Practice','lesson_ids':[second]}]}
        cid=self.call('POST','/curricula',body,201)['id']
        self.user();c,h=self.as_user('student')
        result=self.call('POST','/curricula/'+cid+'/enroll',client=c,headers=h);pid=result['path_id']
        self.assertEqual(self.call('POST','/curricula/'+cid+'/enroll',client=c,headers=h)['path_id'],pid)
        path=self.call('GET','/paths',client=c,headers=h)['items'][0]
        self.assertEqual(len(path['modules']),2);self.assertEqual(path['minimum_score'],80)
        sid=self.call('POST','/learning/sessions',{'lesson_id':first},201,c,h)['id']
        self.call('POST','/learning/sessions/'+sid+'/complete',{'answers':['wrong']},client=c,headers=h)
        self.assertEqual(self.call('GET','/paths',client=c,headers=h)['items'][0]['completed'],0)
        for lid in [first,second]:
            sid=self.call('POST','/learning/sessions',{'lesson_id':lid},201,c,h)['id']
            self.call('POST','/learning/sessions/'+sid+'/complete',{'answers':['Hello']},client=c,headers=h)
        path=self.call('GET','/paths',client=c,headers=h)['items'][0]
        self.assertEqual(path['completed'],2);self.assertIsNone(path['next_lesson'])
        self.call('PUT','/curricula/'+cid,{**body,'minimum_score':95})
        self.assertEqual(self.call('GET','/paths',client=c,headers=h)['items'][0]['minimum_score'],80)
        self.call('PUT','/paths/'+pid,{'title':'No rewrite','lesson_ids':[first]},409)

    def test_curriculum_validation_ownership_and_published_dependencies(self):
        lid=self.lesson();body={'title':'Private course','modules':[{'title':'One','lesson_ids':[lid]}]}
        cid=self.call('POST','/curricula',body,201)['id']
        self.user();c,h=self.as_user('student')
        self.assertEqual(self.call('GET','/curricula',client=c,headers=h)['items'],[])
        self.call('POST','/curricula/'+cid+'/enroll',expected=404,client=c,headers=h)
        self.call('POST','/curricula',body,403,c,h)
        self.call('POST','/curricula',{**body,'modules':[{'title':'Repeated','lesson_ids':[lid,lid]}]},422)
        scoreless=self.call('POST','/lessons',{'title':'Reading','content':'Read','status':'published'},201)['id']
        self.call('POST','/curricula',{**body,'minimum_score':75,'modules':[{'title':'Reading','lesson_ids':[scoreless]}]},422)
        self.user('teacher','teacher');t,th=self.as_user('teacher')
        self.call('PUT','/curricula/'+cid,body,403,t,th)
        published=self.call('POST','/curricula',{**body,'status':'published','minimum_score':80},201)['id']
        self.call('PUT','/lessons/'+lid,{'title':'Now a reading','content':'Read','status':'published'})
        self.call('POST','/curricula/'+published+'/enroll',expected=409,client=c,headers=h)

if __name__=='__main__':
    import unittest
    unittest.main(verbosity=2)
