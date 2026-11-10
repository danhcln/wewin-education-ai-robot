"""Evidence and permission gates; these tests never exercise a live Cloud adapter."""
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch
import test_portal
from backend import cloud_readiness, db


class CloudReadinessTests(TestCase):
    setUp=test_portal.PortalTests.setUp
    call=test_portal.PortalTests.call
    user=test_portal.PortalTests.user
    as_user=test_portal.PortalTests.as_user

    def robot(self):
        return self.call('GET','/robots')['items'][0]['id']

    def test_readiness_and_guide_are_admin_only_and_robot_scoped(self):
        rid=self.robot();self.user();client,headers=self.as_user('student')
        self.call('GET',f'/robots/{rid}/cloud-connection',expected=403,client=client,headers=headers)
        self.call('GET','/cloud-connection-guide',expected=403,client=client,headers=headers)
        self.call('GET','/robots/absent/cloud-connection',expected=404)
        self.call('GET','/cloud-connection-guide',expected=401,client=test_portal.TestClient(test_portal.app,base_url=test_portal.ORIGIN))
        response=self.client.get('/api/portal/cloud-connection-guide')
        self.assertEqual(response.status_code,200)
        self.assertIn('Developer',response.text)

    def test_readiness_is_read_only_and_does_not_invent_provider_or_agent(self):
        rid=self.robot()
        with db.connection() as conn:
            before=conn.execute('SELECT COUNT(*) FROM robot_cloud_links').fetchone()[0]
        with patch.object(cloud_readiness,'source_cloud_evidence',return_value={'name':'Registry name','external_mapping_source':'unverified'}),patch('socket.create_connection',side_effect=AssertionError('No network permitted')):
            result=self.call('GET',f'/robots/{rid}/cloud-connection')['readiness']
        self.assertFalse(result['ready']);self.assertFalse(result['cloud_requests_sent'])
        self.assertFalse(result['apply_supported']);self.assertNotIn('agent_reference',result['registry'])
        checks={c['code']:c['status'] for c in result['checks']}
        self.assertEqual(checks['provider_binding'],'missing');self.assertEqual(checks['agent_mapping'],'missing')
        with db.connection() as conn:
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM robot_cloud_links').fetchone()[0],before)
            self.assertEqual(conn.execute('SELECT COUNT(*) FROM config_observations').fetchone()[0],0)

    def test_registry_ready_claim_and_secret_presence_cannot_unlock_apply(self):
        rid=self.robot()
        profile={'version':0,'provider':'XiaoZhi','agent_reference':'requested-agent','origin':'https://xiaozhi.me','documentation_url':'https://xiaozhi.me/docs','credential_env':'WEWIN_CLOUD_READINESS_TEST'}
        self.call('PUT',f'/robots/{rid}/cloud-connection',profile)
        evidence={'site_id':'site','integration_site_id':'site','enabled':1,'provider':'xiaozhi','external_device_id':'device','agent_reference':'different-agent','external_mapping_source':'provider_verified','authorization_state':'ready'}
        with patch.object(cloud_readiness,'source_cloud_evidence',return_value=evidence),patch.dict('os.environ',{'WEWIN_CLOUD_READINESS_TEST':'secret-value-not-for-ui'}):
            result=self.call('GET',f'/robots/{rid}/cloud-connection')
        checks={c['code']:c['status'] for c in result['readiness']['checks']}
        self.assertEqual(checks['agent_mapping'],'conflict')
        self.assertEqual(checks['management_authorization'],'unverified')
        self.assertEqual(checks['server_credential'],'present_unverified')
        self.assertFalse(result['capabilities']['apply_supported']);self.assertFalse(result['readiness']['ready'])
        self.assertNotIn('secret-value-not-for-ui',json.dumps(result))
        evidence['agent_reference']='requested-agent';evidence['integration_site_id']='another-tenant'
        with patch.object(cloud_readiness,'source_cloud_evidence',return_value=evidence):
            result=self.call('GET',f'/robots/{rid}/cloud-connection')['readiness']
        self.assertEqual(next(c['status'] for c in result['checks'] if c['code']=='agent_mapping'),'missing')

    def test_registry_projection_excludes_secret_columns_and_url_credentials(self):
        path=Path(self.folder.name)/'registry.sqlite3'
        with closing(sqlite3.connect(path)) as conn, conn:
            conn.executescript('''CREATE TABLE robots(id,name,site_id,wire_id,external_device_id,external_mapping_source,external_verified_at,integration_id,pairing_state);
                CREATE TABLE integrations(id,provider,agent_reference,endpoint_origin,enabled,authorization_state,authorization_observed_at,revoked_at,site_id,credential_ref);
                CREATE TABLE robot_observations(robot_id,observed_at,evidence_source,firmware_version);''')
            conn.execute("INSERT INTO robots VALUES('robot','Robot','site','wire','external','operator_verified',1,'integration','active')")
            conn.execute("INSERT INTO integrations VALUES('integration','xiaozhi','agent',?,1,'ready',1,NULL,'site','private-secret-reference')",('https://user:private-password@xiaozhi.me/api?token=private-query#private-fragment',))
        with patch.object(cloud_readiness,'SOURCE_DB',path):
            result=cloud_readiness.source_cloud_evidence('robot')
            self.assertEqual(cloud_readiness.source_cloud_evidence('missing'),{})
        self.assertEqual(result['endpoint_host'],'xiaozhi.me')
        for secret in ('credential_ref','private-secret-reference','private-password','private-query','private-fragment'):
            self.assertNotIn(secret,json.dumps(result))

    def test_missing_registry_is_reported_without_claiming_cloud_timeout(self):
        rid=self.robot()
        with patch.object(cloud_readiness,'SOURCE_DB',Path(self.folder.name)/'missing.sqlite3'):
            result=self.call('GET',f'/robots/{rid}/cloud-connection')['readiness']
        self.assertTrue(result['registry']['unavailable']);self.assertFalse(result['ready'])
        self.assertFalse(result['cloud_requests_sent'])
