import unittest
from unittest.mock import patch
from src.media.youtube import MediaError


class EnrollmentProofTests(unittest.TestCase):
    def setUp(self):
        from tests.test_devices_auth import DeviceAuthTests
        DeviceAuthTests.setUp(self)

    def challenge(self):
        return self.engine.create_challenge(self.site_id,self.principal_id,self.wire_id,self.fingerprint,self.public_key)

    def confirm(self,ch,**kwargs):
        from tests.test_devices_auth import physical_signature
        return self.engine.confirm_challenge(ch['challenge_id'],self.principal_id,ch['display_code'],
            device_signature=physical_signature(self.key,ch['challenge_id'],ch['display_code'],self.wire_id,self.fingerprint),**kwargs)

    def test_boolean_is_not_physical_proof(self):
        ch=self.challenge()
        with self.assertRaisesRegex(ValueError,'physical_proof_invalid'):
            self.engine.confirm_challenge(ch['challenge_id'],self.principal_id,ch['display_code'],codes_match=True)
        self.assertFalse(self.registry.is_authorized(self.wire_id,self.fingerprint))

    def test_wrong_principal_expiry_and_replay(self):
        ch=self.challenge()
        with self.assertRaisesRegex(ValueError,'wrong_enrollment_principal'):
            self.engine.confirm_challenge(ch['challenge_id'],'someone-else',ch['display_code'])
        self.confirm(ch)
        with self.assertRaisesRegex(ValueError,'challenge_not_pending'):self.confirm(ch)
        ch=self.challenge()
        with patch.object(self.engine,'_now_ms',return_value=ch['expires_at']):
            with self.assertRaisesRegex(ValueError,'challenge_expired'):self.confirm(ch)

    def test_failed_registry_commit_keeps_challenge_pending(self):
        ch=self.challenge()
        original=self.registry.enroll_robot
        def failed(**kwargs):
            original(**kwargs)
            raise RuntimeError('simulated commit failure')
        with patch.object(self.registry,'enroll_robot',side_effect=failed):
            with self.assertRaises(RuntimeError):self.confirm(ch)
        self.assertEqual(self.engine.get_challenge(ch['challenge_id'])['state'],'pending')
        self.assertFalse(self.registry.is_authorized(self.wire_id,self.fingerprint))
        self.confirm(ch)

    def test_cross_site_challenge_denied(self):
        with self.assertRaisesRegex(ValueError,'site_access_denied'):
            self.engine.create_challenge('unowned-site',self.principal_id,self.wire_id,self.fingerprint,self.public_key)


class MappingTests(unittest.TestCase):
    def test_revision_conflict_revoke_and_unrelated_asset(self):
        import json,tempfile
        from pathlib import Path
        from src.media.asset_service import AssetService
        fixture=Path(r'E:\WeWIN_Firmware_Lab\audio\manifest.json')
        manifest=json.loads(fixture.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as temp:
            service=AssetService(temp)
            service.import_manifest(manifest,fixture.parent)
            service.import_manifest({**manifest,'asset_id':'second'},fixture.parent)
            with self.assertRaises(MediaError):service.set_mapping('wewin-test-1','2_IweGD2uM4',1)
            service.set_mapping('wewin-test-1','2_IweGD2uM4',1,True)
            with self.assertRaisesRegex(MediaError,'Asset đã thay đổi'):service.set_mapping('wewin-test-1',None,1,True)
            with self.assertRaises(MediaError):service.set_mapping('second','2_IweGD2uM4',1,True)
            service.set_mapping('wewin-test-1',None,2,True,True)
            with self.assertRaises(MediaError):service.for_video('2_IweGD2uM4')
            service.set_mapping('second','AbCdEf01234',1,True)
            self.assertEqual(service.for_video('AbCdEf01234')[0]['asset_id'],'second')


class MappingApiTests(unittest.TestCase):
    def setUp(self):
        from tests.test_voice_media_api import VoiceApiTests
        VoiceApiTests.setUp(self)

    def test_mapping_auth_csrf_channel_schema_and_revision(self):
        import json,tempfile
        from pathlib import Path
        from unittest.mock import Mock
        from tests.test_voice_media_api import VoiceApiTests
        from src.media.asset_service import AssetService
        url='/api/education/assets/wewin-test-1/mapping'
        body={'video_id':'2_IweGD2uM4','expected_revision':1,'content_and_rights_confirmed':True}
        self.assertEqual(self.client.get('/api/education/assets').status_code,401)
        VoiceApiTests.login(self)
        fixture=Path(r'E:\WeWIN_Firmware_Lab\audio\manifest.json')
        with tempfile.TemporaryDirectory() as temp:
            service=AssetService(temp)
            service.import_manifest(json.loads(fixture.read_text(encoding='utf-8')),fixture.parent)
            provider=Mock()
            provider.resolve_channel.return_value={'channel_id':'official'}
            provider.video.return_value={'channel_id':'other'}
            with patch('src.media.education_routes.get_assets',return_value=service),patch('src.media.education_routes.provider',return_value=provider):
                inventory=self.client.get('/api/education/assets').json()['assets']
                self.assertNotIn('output_path',inventory[0])
                self.assertEqual(self.client.post(url,json=body).status_code,403)
                self.assertEqual(self.client.post(url,headers=self.headers,json={**body,'video_id':'bad'}).status_code,422)
                self.assertEqual(self.client.post(url,headers=self.headers,json=body).status_code,409)
                provider.video.return_value={'channel_id':'official'}
                self.assertEqual(self.client.post(url,headers=self.headers,json=body).status_code,200)
                self.assertEqual(self.client.post(url,headers=self.headers,json=body).status_code,409)
                revoked=self.client.post(url,headers=self.headers,json={'expected_revision':2,'revoke':True,'content_and_rights_confirmed':True})
                self.assertEqual(revoked.status_code,200)
                with self.assertRaises(MediaError):service.for_video(body['video_id'])
