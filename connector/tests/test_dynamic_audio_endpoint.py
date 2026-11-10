"""Dynamic source authority and server tests; temp keys/manifests and mocked LAN."""
import json
import os
from pathlib import Path
import tempfile
import time
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import ec,utils
from cryptography.exceptions import InvalidSignature
from src.media import audio_endpoint as endpoint


class DynamicAudioTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory(prefix='wewin-audio-authority-')
        self.addCleanup(self.temporary.cleanup)
        self.root=Path(self.temporary.name)
        self.key=ec.generate_private_key(ec.SECP256R1())
        self.path=self.root/'key.pem'
        self.path.write_bytes(self.key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
        self.now=int(time.time())
        self.data={'asset_id':'wewin-test-1','audio_url':'http://192.168.2.6:9842/wewin-audio/test.ogg',
                   'mode':'lan','sha256':'a'*64,'expires_at':self.now+120}

    def verify(self,descriptor):
        raw=bytes.fromhex(descriptor['signature']);r=int.from_bytes(raw[:32],'big');s=int.from_bytes(raw[32:],'big')
        payload=endpoint.canonical_descriptor(**{k:v for k,v in descriptor.items() if k!='signature'})
        self.key.public_key().verify(utils.encode_dss_signature(r,s),payload,ec.ECDSA(hashes.SHA256()))

    def test_sign_verify_and_no_secret_in_descriptor(self):
        signed=endpoint.sign_descriptor(self.path,**self.data)
        self.verify(signed)
        self.assertEqual(len(signed['signature']),128)
        self.assertNotIn('PRIVATE KEY',json.dumps(signed))
        self.assertNotIn('token',signed['audio_url'])

    def test_tampering_every_authorized_field_invalidates_signature(self):
        signed=endpoint.sign_descriptor(self.path,**self.data)
        for key,value in [('audio_url','http://192.168.9.8:8765/wewin-audio/test.ogg'),
                          ('sha256','b'*64),('expires_at',self.now+121),('mode','https')]:
            with self.subTest(field=key),self.assertRaises((InvalidSignature,ValueError)):
                self.verify({**signed,key:value})

    def test_two_networks_and_ports_without_firmware_rebuild(self):
        for host,port in [('192.168.2.6',9842),('10.20.30.40',17171),('172.16.4.5',9001)]:
            descriptor=endpoint.sign_descriptor(self.path,**{**self.data,'audio_url':f'http://{host}:{port}{endpoint.ROUTE}'})
            self.verify(descriptor)

    def test_production_https_descriptor(self):
        self.verify(endpoint.sign_descriptor(self.path,**{**self.data,'mode':'https',
                                                         'audio_url':'https://audio.wewin.edu.vn'+endpoint.ROUTE}))

    def test_invalid_urls(self):
        forbidden=['file:///etc/passwd','ftp://example.com/a','http://127.0.0.1:8765'+endpoint.ROUTE,
                   'http://169.254.169.254:8765'+endpoint.ROUTE,'http://192.168.2.6:80'+endpoint.ROUTE,
                   'http://192.168.2.6:8765/.env','http://192.168.2.6:8765'+endpoint.ROUTE+'?token=secret',
                   'http://user:pass@192.168.2.6:8765'+endpoint.ROUTE,'http://192.168.2.6:8765/%2e%2e/.env',
                   'http://localhost:8765'+endpoint.ROUTE,'http://192.168.2.6:8765'+endpoint.ROUTE+'#frag',
                   'http://192.168.2.6:8765/'+('x'*512),'http://192.168.002.6:8765'+endpoint.ROUTE,
                   'http://192.168.2.6:8765\\evil'+endpoint.ROUTE,'http://192.168.2.6:8765\r\n'+endpoint.ROUTE]
        for url in forbidden:
            with self.subTest(url=url),self.assertRaises(ValueError):endpoint.validate_audio_url(url,'lan')
        for host in ['localhost','audio.local','192.168.1.1','127.0.0.1','audio.internal','audio.test','audio.invalid','Audio.example.com']:
            with self.subTest(host=host),self.assertRaises(ValueError):endpoint.validate_audio_url('https://'+host+endpoint.ROUTE,'https')

    def test_ambiguous_lan_requires_explicit_active_choice(self):
        with patch.object(endpoint,'windows_lan_addresses',return_value=['10.1.2.3','192.168.2.6']):
            with self.assertRaises(ValueError):endpoint.select_lan_address()
            self.assertEqual(endpoint.select_lan_address('192.168.2.6'),'192.168.2.6')
            with self.assertRaises(ValueError):endpoint.select_lan_address('192.168.1.7')

    def test_active_runtime_manifest_and_network_change(self):
        config=self.root/'active.json'
        config.write_text(json.dumps({'active':True,'pid':os.getpid(),'mode':'lan',
            'base_url':'http://192.168.2.6:9842','sha256':'a'*64,'active_until':self.now+180}))
        with patch.object(endpoint,'windows_lan_addresses',return_value=['192.168.2.6']):
            result=endpoint.prepare_audio_descriptor('wewin-test-1',config,self.path,self.now)
            self.assertEqual(result['status'],'prepared');self.verify(result['descriptor'])
            self.assertLessEqual(result['descriptor']['expires_at'],self.now+180)
        with patch.object(endpoint,'windows_lan_addresses',return_value=['10.1.2.3']):
            self.assertEqual(endpoint.prepare_audio_descriptor('wewin-test-1',config,self.path,self.now)['status'],
                             'audio_server_network_changed')

    def test_missing_expired_inactive_and_unknown_asset_fail_closed(self):
        self.assertEqual(endpoint.prepare_audio_descriptor('other',self.root/'none',self.path)['status'],'invalid_asset')
        self.assertEqual(endpoint.prepare_audio_descriptor('wewin-test-1',self.root/'none',self.path)['status'],'audio_server_not_ready')
        for active,expiry in [(False,self.now+100),(True,self.now-1)]:
            config=self.root/'expired.json';config.write_text(json.dumps({'active':active,'active_until':expiry}))
            self.assertEqual(endpoint.prepare_audio_descriptor('wewin-test-1',config,self.path,self.now)['status'],'audio_server_not_ready')

    def test_mcp_schema_has_no_caller_url(self):
        schema=endpoint.AUDIO_TOOL_DEFINITION['inputSchema']
        self.assertEqual(set(schema['properties']),{'asset_id'})
        self.assertFalse(schema['additionalProperties'])

    def test_mcp_dispatcher_not_ready_without_server_never_signs_caller_url(self):
        from src.mcp.tools import execute_tool,TOOL_DEFINITIONS
        self.assertIn('wewin_prepare_audio',{tool['name'] for tool in TOOL_DEFINITIONS})
        with patch.dict(os.environ,{'WEWIN_AUDIO_ENDPOINT_FILE':str(self.root/'missing.json')}):
            result=json.loads(execute_tool('wewin_prepare_audio',{'asset_id':'wewin-test-1',
                               'audio_url':'http://127.0.0.1:8000/.env'}))
        self.assertEqual(result['status'],'audio_server_not_ready')
        self.assertNotIn('descriptor',result)

    def test_canonical_payload_stable_ascii(self):
        self.assertEqual(endpoint.canonical_descriptor(**self.data).decode(),
             f"wewin-audio-v1\nwewin-test-1\n{self.data['audio_url']}\nlan\n{'a'*64}\n{self.data['expires_at']}")

    def test_server_plan_detects_current_address_without_opening_socket(self):
        import contextlib,io,sys
        from src.media.audio_server import main
        with patch.object(endpoint,'windows_lan_addresses',return_value=['10.2.3.4']),\
             patch.object(sys,'argv',['audio-server','--plan','--port','17171']),\
             patch('src.media.audio_server.AudioServer',side_effect=AssertionError('No listener allowed')),\
             contextlib.redirect_stdout(io.StringIO()) as output:
            main()
        result=json.loads(output.getvalue())
        self.assertEqual(result['audio_url'],'http://10.2.3.4:17171/wewin-audio/test.ogg')
        self.assertFalse(result['listener_started'])

if __name__=='__main__':unittest.main()
