"""Real OS process lock; fake bridge coroutine; no network, scheduler or real secrets."""
from pathlib import Path
import os
import subprocess
import sys
import tempfile
import time
import unittest

ROOT=Path(__file__).resolve().parent.parent

class BridgeSingletonTests(unittest.TestCase):
    def test_real_cloud_bridge_single_instance_and_crash_recovery(self):
        with tempfile.TemporaryDirectory(prefix='wewin-bridge-lock-') as name:
            folder=Path(name);children=[]
            env={**os.environ,'PYTHONPATH':str(ROOT),'BRIDGE_SINGLETON_PATH':str(folder/'bridge.lock'),
                'XIAOZHI_MCP_ENDPOINT':'wss://fixture.invalid/','XIAOZHI_MCP_TOKEN':'synthetic-fixture-credential',
                'XIAOZHI_MCP_ENDPOINT_FILE':'','XIAOZHI_MCP_TOKEN_FILE':'','ADMIN_SYNC_TOKEN':'x'*32,'ADMIN_SYNC_TOKEN_FILE':'',
                'AUTO_SYNC_ENABLED':'false','SYNC_SCHEDULE_ARMED':'false','DATABASE_PATH':str(folder/'unused.db')}
            script="""import os,asyncio
from pathlib import Path
import run_bridge
async def fake_run(self):
 Path(os.environ['BRIDGE_TEST_MARKER']).write_text('guard acquired')
 await asyncio.sleep(30)
run_bridge.XiaoZhiMcpBridge.run=fake_run
run_bridge.main()
"""
            def start(label):
                marker=folder/label;process=subprocess.Popen([sys.executable,'-B','-c',script],cwd=folder,
                    env={**env,'BRIDGE_TEST_MARKER':str(marker)},stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                    **({'creationflags':subprocess.CREATE_NO_WINDOW} if os.name=='nt' else {}));children.append(process);return process,marker
            def wait_marker(process,marker):
                for _ in range(150):
                    if marker.exists():return
                    if process.poll() is not None:break
                    time.sleep(.05)
                self.fail('Fake bridge did not acquire OS lock')
            try:
                first,marker=start('first');wait_marker(first,marker)
                second,other=start('second');out,error=second.communicate(timeout=10)
                self.assertEqual(second.returncode,0);self.assertFalse(other.exists());self.assertIn(b'already running',out)
                first.terminate();first.communicate(timeout=5)
                third,recovered=start('third');wait_marker(third,recovered)
                self.assertTrue(recovered.exists())
            finally:
                for child in children:
                    if child.poll() is None:child.terminate()
                    child.communicate(timeout=5)

if __name__=='__main__':unittest.main(verbosity=2)
