"""First-party Portal inventory; isolated SQLite, scoped mock AI transport."""
from unittest import TestCase
from unittest.mock import patch
from fastapi import HTTPException
import test_portal
from backend import db
from backend.managed_robots import migrate_managed,scoped_adapter
from backend.self_hosted import SelfHostedAdapter


class ManagedPortalTests(TestCase):
    setUp=test_portal.PortalTests.setUp
    call=test_portal.PortalTests.call
    user=test_portal.PortalTests.user
    as_user=test_portal.PortalTests.as_user

    def body(self,kind='simulator'):
        return {'name':'WeWIN QA owned robot','device_id':'qa-managed-device','client_id':'qa-managed-client','kind':kind,'ownership_evidence':'Isolated QA operator attestation','ownership_attested':True,'confirmed':True}

    def create(self,kind='simulator'):return self.call('POST','/managed-robots',self.body(kind))['id']

    def test_registration_scope_duplicate_and_non_admin(self):
        self.call('POST','/managed-robots',{**self.body(),'ownership_attested':False},422)
        self.user();c,h=self.as_user('student')
        self.call('POST','/managed-robots',self.body(),403,c,h)
        rid=self.create()
        robot=next(r for r in self.call('GET','/robots')['items'] if r['id']==rid)
        self.assertFalse(robot['online']);self.assertEqual(robot['source'],'wewin_managed')
        self.call('POST','/managed-robots',{**self.body(),'device_id':'QA-MANAGED-DEVICE'},409)
        self.call('GET',f'/robots/{rid}/device-gateway',expected=403,client=c,headers=h)
        with db.connection() as conn:
            owner=conn.execute('SELECT * FROM managed_robots WHERE id=?',(rid,)).fetchone()
            self.assertEqual(owner['owner_id'],self.call('GET','/session')['user_id'])
            self.assertEqual(conn.execute('PRAGMA foreign_key_check').fetchall(),[])
        _,adapter=scoped_adapter(rid);self.assertEqual(adapter.link['owner_id'],owner['owner_id'])
        self.assertEqual(adapter.link['tenant_id'],'wewin-local')

    def test_physical_issuance_and_legacy_disconnect_blocked_without_remote_write(self):
        rid=self.create('physical')
        with patch.object(SelfHostedAdapter,'request') as remote:
            self.call('POST',f'/robots/{rid}/device-gateway/provision',{'confirmed':True},403)
            self.call('POST',f'/robots/{rid}/self-hosted/disconnect',{'confirmed':True},409)
            remote.assert_not_called()

    def test_binding_drift_and_unavailable_status_never_promote_online(self):
        rid=self.create();_,adapter=scoped_adapter(rid)
        with patch.object(SelfHostedAdapter,'request',side_effect=HTTPException(504,'QA timeout')):
            status=self.call('GET',f'/robots/{rid}/device-gateway')
            self.assertIn('timeout',status['error'])
            self.assertFalse(next(r for r in self.call('GET','/robots')['items'] if r['id']==rid)['online'])
        with patch.object(SelfHostedAdapter,'request',return_value={'agent_id':'wrong-agent'}):
            with self.assertRaises(HTTPException) as error:adapter.ensure_binding()
            self.assertEqual(error.exception.status_code,409)

    def test_migration_idempotent_preserves_legacy_links_and_allows_shared_agent(self):
        rid=self.create();_,adapter=scoped_adapter(rid)
        with db.connection() as conn:before=[tuple(r) for r in conn.execute('SELECT * FROM self_hosted_links ORDER BY robot_id')]
        migrate_managed()
        with db.connection() as conn:
            self.assertEqual(before,[tuple(r) for r in conn.execute('SELECT * FROM self_hosted_links ORDER BY robot_id')])
            conn.execute('INSERT INTO devices VALUES(?,?,?)',('qa-second','wewin_managed',1))
            conn.execute('INSERT INTO self_hosted_links VALUES(?,?,1,1,?,1)',('qa-second',adapter.link['agent_id'],adapter.link['owner_id']))

    def test_no_legacy_management_origin_or_secret_in_auth_errors(self):
        with patch.dict('os.environ',{'WEWIN_AI_ORIGIN':'https://api.tenclass.net'}):
            with self.assertRaises(HTTPException) as error:SelfHostedAdapter({}).request('GET','/v1/catalog')
            self.assertEqual(error.exception.status_code,503)
