"""Fake service processes/network; real temporary files and OS singleton only."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch
from scripts import windows_services as ops


class FakeSystem:
    def __init__(self, root):
        self.root=Path(root);self.started=[];self.ready=False;self.names={'wewin_prepare_audio'}
        self.state={'backend':[],'bridge':[],'foreign_bridges':[],'listeners':[]}
        self.connected=True

    def inventory(self):return copy.deepcopy(self.state)
    def health(self):return self.ready
    def tools(self):return self.names
    def sleep(self,_seconds):pass
    def spawn(self,role,_config):
        self.started.append(role)
        record={'pid':100 if role=='backend' else 200,'created':time.time()-1,
                'database':str(self.root/'runtime.db'),'status_path':str(self.root/'heartbeat.json')}
        self.state[role].append(record)
        if role=='backend':
            self.ready=True;self.state['listeners']=[{'ip':'127.0.0.1','pid':100}]
        else:
            Path(record['status_path']).write_text(json.dumps({'pid':200,'updated_at':time.time(),
                 'state':'connected' if self.connected else 'not_connected'}))
        return record['pid']


class WindowsStartupTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(prefix='wewin-startup-tests-');self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)
        self.config={'python':Path(sys.executable),'database':self.root/'runtime.db',
                     'bridge_status':self.root/'heartbeat.json','directory':self.root}
        self.system=FakeSystem(self.root)

    def ensure(self):return ops.ensure_services(self.config,self.system,health_attempts=2,bridge_attempts=2)

    def test_01_backend_before_bridge(self):
        result=self.ensure();self.assertEqual(self.system.started,['backend','bridge'])
        self.assertEqual(result['Backend'],'HEALTHY');self.assertEqual(result['BridgeCount'],1)

    def test_02_second_start_reuses_both(self):
        self.ensure();self.system.started.clear();self.ensure();self.assertEqual(self.system.started,[])

    def test_03_existing_unhealthy_not_restarted(self):
        self.system.spawn('backend',self.config);self.system.started.clear();self.system.ready=False
        with self.assertRaises(RuntimeError):self.ensure()
        self.assertEqual(self.system.started,[])

    def test_04_health_timeout_never_starts_bridge(self):
        with patch.object(self.system,'health',return_value=False):
            with self.assertRaises(RuntimeError):self.ensure()
        self.assertEqual(self.system.started,['backend'])

    def test_05_duplicate_bridge_refused(self):
        self.ensure();self.system.state['bridge']*=2;self.system.started.clear()
        with self.assertRaises(RuntimeError):self.ensure()
        self.assertEqual(self.system.started,[])

    def test_06_foreign_bridge_refused(self):
        self.system.state['foreign_bridges']=[{'pid':999}]
        with self.assertRaises(RuntimeError):self.ensure()
        self.assertEqual(self.system.started,[])

    def test_07_disconnected_bridge_keeps_reconnect_owner(self):
        self.system.connected=False
        with self.assertRaises(RuntimeError):self.ensure()
        self.assertEqual(self.system.started,['backend','bridge'])
        self.system.started.clear()
        with self.assertRaises(RuntimeError):self.ensure()
        self.assertEqual(self.system.started,[])

    def test_08_foreign_port_refused(self):
        self.system.state['listeners']=[{'ip':'127.0.0.1','pid':999}]
        with self.assertRaises(RuntimeError):self.ensure()
        self.assertEqual(self.system.started,[])

    def test_09_backend_wrong_listener_refused(self):
        self.system.spawn('backend',self.config);self.system.started.clear()
        self.system.state['listeners'][0]['pid']=999
        with self.assertRaises(RuntimeError):self.ensure()
        self.assertEqual(self.system.started,[])

    def test_10_non_loopback_refused(self):
        self.system.spawn('backend',self.config);self.system.started.clear()
        self.system.state['listeners'][0]['ip']='0.0.0.0'
        with self.assertRaises(RuntimeError):self.ensure()
        self.assertEqual(self.system.started,[])

    def test_11_old_backend_needs_manual_activation(self):
        self.system.names=set()
        with self.assertRaises(RuntimeError):self.ensure()
        self.assertEqual(self.system.started,['backend'])

    def test_12_environment_disables_all_sync_and_debug(self):
        with patch.dict(os.environ,{'AUTO_SYNC_ENABLED':'true','SYNC_SCHEDULE_ARMED':'true','DEBUG':'true'}):
            value=ops.service_environment(self.config)
        for key in ('AUTO_SYNC_ENABLED','SYNC_SCHEDULE_ARMED','DEBUG'):self.assertEqual(value[key],'false')
        self.assertEqual(value['DATABASE_PATH'],str(self.config['database']))

    def test_13_fresh_heartbeat(self):
        self.ensure();self.assertEqual(ops.bridge_state(self.system.state['bridge'][0]),'CONNECTED')

    def test_14_stale_heartbeat(self):
        self.ensure();record=self.system.state['bridge'][0]
        self.assertEqual(ops.bridge_state(record,now=time.time()+60),'UNKNOWN')

    def test_15_reused_pid_and_future_heartbeat(self):
        self.ensure();record=self.system.state['bridge'][0]
        record['created']=time.time()+5
        self.assertEqual(ops.bridge_state(record),'UNKNOWN')
        record['created']=0
        self.assertEqual(ops.bridge_state(record,now=time.time()-10),'UNKNOWN')

    def test_16_wrong_pid_missing_and_oversized_status(self):
        self.ensure();record=self.system.state['bridge'][0];record['pid']=300
        self.assertEqual(ops.bridge_state(record),'UNKNOWN')
        path=Path(record['status_path']);path.write_text('x'*3000)
        self.assertEqual(ops.bridge_state(record),'UNKNOWN')
        path.unlink();self.assertEqual(ops.bridge_state(record),'UNKNOWN')

    def test_17_profile_mismatch_reported_without_restarting(self):
        self.ensure();self.system.state['bridge'][0]['database']=str(self.root/'other.db')
        self.system.started.clear();result=self.ensure()
        self.assertFalse(result['ConfiguredProfileMatches']);self.assertEqual(self.system.started,[])

    def test_18_spawn_pinned_command_hidden_no_secret(self):
        process=type('Process',(),{'pid':77})()
        with patch('subprocess.Popen',return_value=process) as spawn:
            ops.WindowsSystem().spawn('backend',self.config)
        argv=spawn.call_args.args[0];kw=spawn.call_args.kwargs
        self.assertEqual(argv[0],sys.executable);self.assertIn('127.0.0.1',argv)
        self.assertNotIn('--reload',argv);self.assertEqual(kw['creationflags'],subprocess.CREATE_NO_WINDOW)
        self.assertEqual(kw['env']['AUTO_SYNC_ENABLED'],'false')

    def test_19_check_and_plan_never_spawn(self):
        with patch.object(ops,'load_config',return_value=self.config),patch.object(ops,'WindowsSystem',return_value=self.system),\
             patch.object(sys,'argv',['launcher','--dry-run']),contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(ops.main(),0)
        self.assertFalse(json.loads(output.getvalue())['starts_processes']);self.assertEqual(self.system.started,[])

    def test_20_error_does_not_echo_exception_secret(self):
        with (patch.object(ops,'load_config',side_effect=ValueError('NEVER_PRINT_SECRET')),
              patch.object(sys,'argv',['launcher','--check']),
              contextlib.redirect_stdout(io.StringIO()) as output):
            self.assertEqual(ops.main(),1)
        self.assertNotIn('NEVER_PRINT_SECRET',output.getvalue())

    def test_21_config_rejects_secrets_and_production_database(self):
        config=self.root/'config.json';config.write_text(json.dumps({'token':'NEVER_PRINT_SECRET'}))
        with self.assertRaises(ValueError):ops.load_config(config)
        path=self.root/'existing.db';path.write_text('fixture')
        config.write_text(json.dumps({'python':sys.executable,'database':str(path),
                          'bridge_status':str(self.root/'heartbeat.json'),'directory':str(self.root)}))
        with self.assertRaises(ValueError):ops.load_config(config)

    def test_22_real_os_launcher_lock_two_processes(self):
        script='''import sys,time\nfrom pathlib import Path\nfrom src.sync.locking import SyncLock,SyncAlreadyRunningError\nfrom tests.test_windows_startup import FakeSystem\nfrom scripts.windows_services import ensure_services\np=Path(sys.argv[1]);guard=SyncLock(p/'launcher.lock')\ntry:guard.acquire('fake-startup')\nexcept SyncAlreadyRunningError:sys.exit(0)\ntry:\n if sys.argv[2]=='contender':sys.exit(9)\n (p/'held').write_text('ready')\n for _ in range(500):\n  if (p/'release').exists():break\n  time.sleep(.02)\n system=FakeSystem(p);config={'database':p/'runtime.db'}\n ensure_services(config,system,health_attempts=2,bridge_attempts=2)\n with (p/'trace').open('a') as f:f.write(','.join(system.started)+'\\n')\nfinally:guard.release()\n'''
        first=subprocess.Popen([sys.executable,'-B','-c',script,str(self.root),'holder'],cwd=ops.ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        for _ in range(100):
            if (self.root/'held').exists():break
            time.sleep(.02)
        second=subprocess.Popen([sys.executable,'-B','-c',script,str(self.root),'contender'],cwd=ops.ROOT,stdout=subprocess.PIPE,stderr=subprocess.PIPE)
        try:
            out,err=second.communicate(timeout=15);self.assertEqual(second.returncode,0,err.decode(errors='replace'))
        finally:(self.root/'release').write_text('release')
        out,err=first.communicate(timeout=15);self.assertEqual(first.returncode,0,err.decode(errors='replace'))
        self.assertEqual((self.root/'trace').read_text().splitlines(),['backend,bridge'])

    def test_23_powershell_syntax_and_task_policy(self):
        files=['start_wewin_services.ps1','check_wewin_services.ps1','manage_control_center_startup.ps1']
        for name in files:
            path=ops.ROOT/'scripts'/name
            command="$tokens=$null;$errors=$null;[System.Management.Automation.Language.Parser]::ParseFile('"+str(path)+"',[ref]$tokens,[ref]$errors)|Out-Null;if($errors.Count){exit 1}"
            result=subprocess.run(['powershell','-NoProfile','-NonInteractive','-Command',command],capture_output=True,timeout=15)
            self.assertEqual(result.returncode,0,result.stderr)
        source=(ops.ROOT/'scripts/manage_control_center_startup.ps1').read_text(encoding='utf-8-sig')
        for value in ('Interactive','Limited','IgnoreNew','-RestartCount 3','PT15S','pythonw.exe'):
            self.assertIn(value,source)
        self.assertNotIn('ExecutionPolicy Bypass',source);self.assertNotIn('-WakeToRun',source)

    def test_24_exported_task_is_disabled_and_no_credentials(self):
        from scripts.windows_task_definition import task_xml,NS
        import xml.etree.ElementTree as ET
        tree=ET.fromstring(task_xml(self.config,'S-1-5-21-111-222-333-1001',self.root))
        ns={'t':NS}
        self.assertEqual(tree.find('t:Settings/t:Enabled',ns).text,'false')
        self.assertEqual(tree.find('t:Settings/t:WakeToRun',ns).text,'false')
        self.assertEqual(tree.find('t:Settings/t:MultipleInstancesPolicy',ns).text,'IgnoreNew')
        self.assertEqual(tree.find('t:Principals/t:Principal/t:LogonType',ns).text,'InteractiveToken')
        self.assertNotIn('token=',ET.tostring(tree,encoding='unicode'))

    def test_25_down_check_nonzero_without_start(self):
        with (patch.object(ops,'load_config',return_value=self.config),
              patch.object(ops,'WindowsSystem',return_value=self.system),
              patch.object(sys,'argv',['launcher','--check']),contextlib.redirect_stdout(io.StringIO())):
            self.assertEqual(ops.main(),2)
        self.assertEqual(self.system.started,[])


if __name__=='__main__':unittest.main()
