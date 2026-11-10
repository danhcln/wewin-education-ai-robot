"""Direct route tests; mocks only, no production DB or capture."""
import threading
import unittest
from unittest.mock import Mock, patch
from starlette.requests import Request
from fastapi import HTTPException
import os, tempfile
_test_root=tempfile.TemporaryDirectory()
os.environ["DATABASE_PATH"]=_test_root.name+"/knowledge.db"
os.environ["BROWSER_SESSION_STORE"]=_test_root.name+"/.secrets/browser.sqlite3"
os.environ["AUTO_SYNC_ENABLED"]="false"
os.environ["SYNC_SCHEDULE_ARMED"]="false"
import src.api.app
from src.streaming.routes import direct_auth, direct_start, direct_status, Start

def request(peer="127.0.0.1"):
 return Request({"type":"http","method":"POST","scheme":"http","path":"/","headers":[(b"host",b"127.0.0.1")],"client":(peer,123),"server":("127.0.0.1",80)})
class DirectTests(unittest.TestCase):
 def test_localhost(self):
  with self.assertRaises(HTTPException):direct_auth(request("192.168.2.2"),True)
 def test_auth_csrf(self):
  with patch("src.streaming.routes.get_store") as store:
   direct_auth(request(),True);store.return_value.authorize.assert_called_once()
   self.assertTrue(store.return_value.authorize.call_args.args[1])
 def test_invocation_observed_ip_no_descriptor_response(self):
  media=Mock(lock=threading.RLock(),jobs=[],generation=4);media.status.return_value={"state":"IDLE"}
  control=Mock();control.device.return_value={"ip":"192.168.2.57"}
  stream=Mock();stream.start.return_value={"descriptor":{"private":"never returned"}};stream.status.return_value={"state":"CONNECTING"}
  with patch("src.streaming.routes.direct_auth"),patch("src.media.device_control.get_control",return_value=control),patch("src.media.orchestration.get_session",return_value=media),patch("src.streaming.routes.get_service",return_value=stream):
   result=direct_start(Start(endpoint=3,peer_ipv4="10.0.0.99",allow_system_mix=True,local_output_routed_away=True),request())
  self.assertNotIn("descriptor",result);self.assertEqual(stream.start.call_args.kwargs["peer_ipv4"],"192.168.2.57")
  control.send.assert_called_once_with("start",5,{"private":"never returned"})
 def test_playing_needs_output(self):
  stream=Mock();stream.status.return_value={"state":"PLAYING","packets_sent":5,"device_report":{"state":"PLAYING","output_frames":0}}
  with patch("src.streaming.routes.direct_auth"),patch("src.streaming.routes.get_service",return_value=stream),patch("src.media.device_control.get_control"):
   self.assertEqual(direct_status(request())["state"],"CAPTURING")
