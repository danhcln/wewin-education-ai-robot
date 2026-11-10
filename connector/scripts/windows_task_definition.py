"""Build a DISABLED Task Scheduler review artifact. Never registers/runs a task."""
from pathlib import Path
import re
import xml.etree.ElementTree as ET

NS = 'http://schemas.microsoft.com/windows/2004/02/mit/task'
ET.register_namespace('', NS)


def task_xml(config, user_sid, root):
    if not re.fullmatch(r'S-1-5-[0-9-]+', user_sid):
        raise ValueError('Expected the current Windows user SID')
    root = Path(root)
    task = ET.Element('{'+NS+'}Task', version='1.4')
    def child(parent, tag, text=None, **attributes):
        value=ET.SubElement(parent,'{'+NS+'}'+tag,attributes)
        if text is not None:value.text=str(text)
        return value
    info=child(task,'RegistrationInfo')
    child(info,'Description','WeWIN Control Center optional Auto Start (Phase7D.1B.2C)')
    child(info,'Author','WeWIN local operator')
    trigger=child(child(task,'Triggers'),'LogonTrigger')
    child(trigger,'Enabled','true');child(trigger,'UserId',user_sid);child(trigger,'Delay','PT15S')
    principal=child(child(task,'Principals'),'Principal',id='CurrentUser')
    child(principal,'UserId',user_sid);child(principal,'LogonType','InteractiveToken')
    child(principal,'RunLevel','LeastPrivilege')
    settings=child(task,'Settings')
    for name,value in [('MultipleInstancesPolicy','IgnoreNew'),('DisallowStartIfOnBatteries','false'),
                       ('StopIfGoingOnBatteries','false'),('AllowHardTerminate','false'),
                       ('StartWhenAvailable','true'),('RunOnlyIfNetworkAvailable','false'),
                       ('AllowStartOnDemand','true'),('Enabled','false'),('Hidden','false'),
                       ('WakeToRun','false'),('ExecutionTimeLimit','PT0S'),('Priority','7')]:
        child(settings,name,value)
    retry=child(settings,'RestartOnFailure');child(retry,'Interval','PT1M');child(retry,'Count','3')
    action=child(child(task,'Actions',Context='CurrentUser'),'Exec')
    child(action,'Command',Path(config['python']).with_name('pythonw.exe'))
    child(action,'Arguments',f'-B "{root / "scripts/start_control_center.py"}" --config "{root / ".maintenance/control-center/startup-config.json"}"')
    child(action,'WorkingDirectory',root)
    return ET.tostring(task,encoding='utf-16',xml_declaration=True)
