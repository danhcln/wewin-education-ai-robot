"""Actual catalog/asset integration, isolated from credentials and production stores."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from src.media.asset_service import AssetService
from src.media.youtube import YouTubeClient, MediaError


class EducationTests(unittest.TestCase):
    def test_authorized_fixture_import_integrity_and_no_fake_mapping(self):
        fixture = Path(r'E:\WeWIN_Firmware_Lab\audio\manifest.json')
        record = json.loads(fixture.read_text(encoding='utf-8'))
        with tempfile.TemporaryDirectory() as temp:
            service = AssetService(temp)
            imported = service.import_manifest(record, fixture.parent)
            self.assertIsNone(imported['youtube_video_id'])
            self.assertEqual(service.get('wewin-test-1')[0]['sha256'], record['output_sha256'])
            with self.assertRaises(MediaError):
                service.for_video('2_IweGD2uM4')
            with self.assertRaises(ValueError):
                service.import_manifest(record, fixture.parent)

    def test_rights_root_hash_and_mapping_validation(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / 'audio.ogg'
            source.write_bytes(Path(r'E:\WeWIN_Firmware_Lab\audio\wewin-test-1.ogg').read_bytes())
            record = dict(asset_id='owned', user_authorized=True, youtube_source=False,
                          output_path=str(source), output_sha256=hashlib.sha256(source.read_bytes()).hexdigest())
            service = AssetService(root / 'store')
            for bad in ({'user_authorized': False}, {'youtube_source': True},
                        {'output_sha256': '0'*64}, {'youtube_video_id': '2_IweGD2uM4'}):
                with self.assertRaises(ValueError):
                    service.import_manifest({**record, **bad}, root)
            service.import_manifest({**record, 'youtube_video_id':'2_IweGD2uM4', 'mapping_verified':True}, root)
            self.assertEqual(service.for_video('2_IweGD2uM4')[0]['asset_id'], 'owned')
            source_in_store = service.get('owned')[1]
            source_in_store.write_bytes(b'corrupt')
            with self.assertRaises(MediaError): service.get('owned')

    def test_playlist_pages_and_scope(self):
        with tempfile.TemporaryDirectory() as temp:
            client = YouTubeClient(key_provider=lambda:'test-key', channel_file=Path(temp)/'channel.json')
            client.channel={'channel_id':'UC'+'a'*22}
            client.resolve_channel=lambda:client.channel
            calls=[]
            def page(resource,params):
                calls.append((resource,params))
                return {'items':[{'id':'PL'+'b'*20,'snippet':{'title':'Animals'}}], 'nextPageToken':'NEXT'}
            client._request_page=page
            first=client.playlists()
            self.assertEqual(first['next_cursor'],'NEXT')
            client.playlists(first['next_cursor'])
            self.assertEqual(calls[-1][1]['pageToken'],'NEXT')
            with self.assertRaises(MediaError): client.playlists(limit=100)
            client._request=lambda *a:[{'snippet':{'channelId':'UC'+'z'*22}}]
            with self.assertRaises(MediaError): client.playlist_items('PL'+'b'*20)

    def test_encoder_source_rejects_network_path(self):
        from src.streaming.asset_source import AssetSource
        with self.assertRaises((OSError, ValueError)):
            AssetSource('https://youtube.com/watch?v=2_IweGD2uM4', lambda p:None)

class EducationApiTests(unittest.TestCase):
    def setUp(self):
        from tests.test_voice_media_api import VoiceApiTests
        VoiceApiTests.setUp(self)

    def login(self):
        from tests.test_voice_media_api import VoiceApiTests
        VoiceApiTests.login(self)

    def test_catalog_requires_authentication(self):
        self.assertEqual(self.client.get('/api/education/lessons').status_code,401)

    def test_authenticated_catalog_and_csrf_queue(self):
        from unittest.mock import Mock, patch
        self.login()
        provider=Mock()
        provider.resolve_channel.return_value={'channel_id':'UC'+'a'*22}
        video={'video_id':'2_IweGD2uM4','channel_id':'UC'+'a'*22,'title':'Approved fixture metadata'}
        provider.latest.return_value={'videos':[video]}
        provider.video.return_value=video
        with patch('src.media.education_routes.provider',return_value=provider):
            answer=self.client.get('/api/education/lessons')
            self.assertEqual(answer.status_code,200)
            self.assertFalse(answer.json()['videos'][0]['playable_on_robot'])
            self.assertEqual(self.client.post('/api/education/queues',json={'video_ids':[video['video_id']]}).status_code,403)
            queued=self.client.post('/api/education/queues',headers=self.headers,json={'video_ids':[video['video_id']]})
            self.assertEqual(queued.status_code,200)
            self.assertEqual(len(queued.json()['items']),1)
            self.assertEqual(self.client.post('/api/education/playback/actions',headers=self.headers,
                json={'action':'play','request_id':'test-request','audio_url':'http://bad.example'}).status_code,422)


class OwnedSessionTests(unittest.TestCase):
    def test_owned_session_play_pause_resume_next_and_duplicate(self):
        import time
        from unittest.mock import patch
        from uuid import uuid4
        from tests.test_voice_media import Browser, Stream, Control, A, B
        from src.media.orchestration import MediaSession
        cid='UC'+'a'*22
        class Provider:
            def video(self, vid): return {**(A if vid==A['video_id'] else B),'channel_id':cid}
            def resolve_channel(self): return {'channel_id':cid}
        class Output(Stream):
            def status(self): return {**super().status(),'device_report':{'output_frames':1,'position_ms':200}}
        events=[]
        stream=Output(events)
        control=Control(stream,events)
        browser=Browser(events)
        browser.connected=False
        with tempfile.TemporaryDirectory() as temp:
            service=AssetService(Path(temp)/'assets')
            fixture=Path(r'E:\WeWIN_Firmware_Lab\audio\manifest.json')
            record=json.loads(fixture.read_text(encoding='utf-8'))
            for index,vid in enumerate((A['video_id'],B['video_id'])):
                service.import_manifest({**record,'asset_id':'lesson'+str(index),
                    'youtube_video_id':vid,'mapping_verified':True},fixture.parent)
            with patch('src.media.asset_service.get_assets',return_value=service):
                session=MediaSession(browser,Provider(),stream,control,lambda:[])
                try:
                    def action(name, **kwargs):
                        body={'action':name,'request_id':uuid4().hex,'owned_audio':True,**kwargs}
                        receipt=session.submit(body)
                        deadline=time.monotonic()+3
                        while time.monotonic()<deadline:
                            status=session.status()
                            if status['generation']==receipt['generation'] and status['state'] in ('PLAYING','PAUSED','IDLE','ERROR'):return body,status
                            time.sleep(.01)
                        self.fail('session timeout')
                    body,status=action('play',video_id=A['video_id'],queue=[A['video_id'],B['video_id']])
                    self.assertEqual(status['state'],'PLAYING')
                    self.assertEqual(session.submit(body)['status'],'duplicate_request')
                    self.assertEqual(action('pause')[1]['state'],'PAUSED')
                    self.assertEqual(action('resume')[1]['state'],'PLAYING')
                    self.assertEqual(action('next')[1]['video_id'],B['video_id'])
                    self.assertEqual(action('stop')[1]['state'],'IDLE')
                    self.assertEqual(action('play',video_id=A['video_id'])[1]['state'],'PLAYING')
                    record=service.get('lesson0')[0]
                    service.set_mapping('lesson0',None,record['revision'],True,True)
                    deadline=time.monotonic()+3
                    while session.status()['state']!='ERROR' and time.monotonic()<deadline:
                        time.sleep(.01)
                    self.assertEqual(session.status()['state'],'ERROR')
                    self.assertEqual(session.status()['last_error'],'rights_revoked')
                    self.assertFalse(any(x.startswith('browser:') for x in events))
                finally: session.shutdown()


class SourceTests(unittest.TestCase):
    def test_real_encoder_pacing_and_cancel(self):
        import os, time
        from unittest.mock import patch
        from src.streaming.asset_source import AssetSource
        ffmpeg=r'E:\WeWIN_Firmware_Lab\dev-venv\Lib\site-packages\imageio_ffmpeg\binaries\ffmpeg-win-x86_64-v7.1.exe'
        packets=[]
        with patch.dict(os.environ, {'WEWIN_STREAM_FFMPEG':ffmpeg}):
            source=AssetSource(r'E:\WeWIN_Firmware_Lab\audio\wewin-test-1.ogg',lambda p:packets.append((time.monotonic(),p)))
            source.start()
            until=time.monotonic()+10
            while len(packets)<8 and time.monotonic()<until: time.sleep(.01)
            source.stop()
        self.assertGreaterEqual(len(packets),8)
        self.assertGreaterEqual(packets[7][0]-packets[0][0],.12)
        self.assertTrue(all(0<len(p)<=1275 for _,p in packets))
        self.assertIsNotNone(source.process.poll())
        self.assertFalse(source.thread.is_alive())

if __name__=='__main__': unittest.main()

