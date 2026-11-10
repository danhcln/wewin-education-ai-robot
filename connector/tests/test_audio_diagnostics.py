"""Loopback-only audit regressions; no production cache or ESP32."""
import hashlib
import http.client
import json
import threading
import unittest
from src.media.audio_server import AudioServer, ROUTE


class AudioDiagnosticsTests(unittest.TestCase):
    def server(self, **kwargs):
        self.events=[]
        service=AudioServer('127.0.0.1',0,'127.0.0.1',b'OggSfixture',
                            min_interval=0,_host_test=True,audit=self.events.append,**kwargs)
        self.addCleanup(service.server_close)
        return service

    def request(self,service,path=ROUTE,method='GET'):
        thread=threading.Thread(target=service.handle_request);thread.start()
        connection=http.client.HTTPConnection(*service.server_address,timeout=3)
        connection.request(method,path)
        response=connection.getresponse();result=(response.status,dict(response.getheaders()),response.read())
        connection.close();thread.join(timeout=4);self.assertFalse(thread.is_alive())
        return result

    def test_success_records_only_socket_delivery_not_hardware(self):
        server=self.server();status,headers,body=self.request(server)
        self.assertEqual(status,200);self.assertEqual(headers['Content-Type'],'audio/ogg')
        self.assertEqual(hashlib.sha256(body).digest(),hashlib.sha256(server.payload).digest())
        event=self.events[-1];self.assertEqual(event['audio_gets'],1)
        self.assertEqual(event['body_bytes'],len(body));self.assertTrue(event['client_match'])
        self.assertNotIn('hardware_pass',event)

    def test_secret_query_never_logged(self):
        server=self.server();status,_,_=self.request(server,ROUTE+'?token=DO_NOT_LOG_THIS')
        self.assertEqual(status,404);self.assertEqual(self.events[-1]['route'],'other')
        self.assertNotIn('DO_NOT_LOG_THIS',json.dumps(self.events));self.assertEqual(server.audio_gets,0)

    def test_wrong_client_still_denied(self):
        server=self.server();server.allowed_client='127.0.0.2'
        self.assertEqual(self.request(server)[0],403)
        self.assertFalse(self.events[-1]['client_match']);self.assertEqual(server.bytes_sent,0)

    def test_head_does_not_count_as_download(self):
        server=self.server();self.assertEqual(self.request(server,method='HEAD')[0],200)
        self.assertEqual(server.audio_gets,0);self.assertEqual(server.bytes_sent,0)

    def test_health_not_audio_download(self):
        server=self.server();self.assertEqual(self.request(server,'/health')[0],200)
        self.assertEqual(server.audio_gets,0);self.assertEqual(self.events[-1]['route'],'health')

    def test_ttl_shutdown_reason(self):
        server=self.server(ttl=1);server.run_until_expired()
        self.assertEqual(self.events[-1]['event'],'server_stopped')
        self.assertEqual(server.stop_reason,'ttl_expired')

    def test_request_limit_still_enforced(self):
        server=self.server(max_requests=1);self.assertEqual(self.request(server)[0],200)
        server.run_until_expired();self.assertEqual(server.stop_reason,'request_limit')

    def test_audit_write_failure_does_not_change_authorization(self):
        server=self.server()
        def broken(_):raise OSError('do not echo secret')
        server.audit=broken;self.assertEqual(self.request(server,'/.env')[0],404)


if __name__=='__main__':unittest.main()
