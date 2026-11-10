"""Offline, allowlisted facts from SAVED logs. No serial/socket/capture imports.

Never exports raw lines, URL paths/query/userinfo, credentials, SSIDs or device IDs.
Firmware attribution resets at each observed boot. A file name is not identity.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
from urllib.parse import urlsplit

PUBLIC_HOSTS=('api.tenclass.net','api.xiaozhi.me','xiaozhi.me','xiaozhi-api.tandev282.workers.dev')
BOOT=re.compile(r'(?:ESP-ROM:|rst:0x|boot:\s*ESP-IDF|boot:\s*chip revision)',re.I)
VERSION=re.compile(r'(?:App version|Application version|Firmware version)\s*:\s*(\d+\.\d+\.\d+)([^\s,;]*)',re.I)
EVENTS=(
    ('mqtt_connect_attempt',r'(?:MqttProtocol|MQTT).*?(?:Connecting to|connect to|connecting[ .:]|connection attempt)'),
    ('mqtt_connected',r'(?:MqttProtocol|MQTT).*?(?:Connected to|connection established|connected successfully)'),
    ('websocket_connect_attempt',r'(?:WebsocketProtocol|WebSocket).*?(?:Connecting to|connect to)'),
    ('websocket_connected',r'(?:WebsocketProtocol|WebSocket).*?(?:Connected to|connection established|connected successfully)'),
    ('mqtt_disconnected',r'(?:MqttProtocol|MQTT).*?disconnected'),
    ('websocket_disconnected',r'(?:WebsocketProtocol|WebSocket).*?disconnected'),
    ('wifi_connected',r'(?:WiFi|Wifi|wifi).*?(?:connected to|got ip|connected with)'),
    ('ota_check_started',r'(?:Ota|OTA).*?(?:Current version:|Checking.*version|check.*version)'),
    ('bluetooth_uart_ack',r'BT RX.*?"(?:cmd|type)"\s*:\s*"response"'),
    ('bluetooth_connected_event',r'(?:BtBridge|BT RX).*?"event"\s*:\s*"connected"'),
)


def endpoint_facts(line):
    items=[]
    for match in re.finditer(r'\b(?:https?|wss?|mqtts?)://[^\s<>"\x27]+',line,re.I):
        try:
            value=urlsplit(match[0].rstrip('.,;)'));host=value.hostname;port=value.port
        except ValueError:continue
        if host not in PUBLIC_HOSTS:continue  # Unknown hosts may themselves encode secrets.
        items.append({'scheme':value.scheme.lower(),'host':host,'port':port or {'https':443,'wss':443,'http':80,'ws':80,'mqtts':8883,'mqtt':1883}.get(value.scheme.lower()),'path_and_credentials_exported':False})
    # Some firmware uses a bare known host:port, with no URI scheme.
    for host in PUBLIC_HOSTS:
        for match in re.finditer(r'(?<![\w.-])'+re.escape(host)+r':(\d{2,5})(?!\d)',line,re.I):
            port=int(match[1])
            if 1<=port<=65535 and not any(v['host']==host and v['port']==port for v in items):items.append({'scheme':'unknown','host':host,'port':port,'path_and_credentials_exported':False})
    return items


def inspect_log(path):
    path=Path(path);data=path.read_bytes();encoding='utf-16' if data.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig';lines=data.decode(encoding,errors='replace').splitlines()
    sessions=[];current=None
    def new_session(line):
        return {'start_line':line,'numeric_app_version':None,'build_family':'UNATTRIBUTED','identity_line':None,'events':[],'protocol_marker_lines':{'mqtt':[],'websocket':[],'udp':[]},'endpoints':[],'attribution':'SAVED_LOG_ONLY_NOT_CURRENT_DEVICE'}
    def observed(session):return bool(session['events'] or session['endpoints'] or any(session['protocol_marker_lines'].values()))
    for number,line in enumerate(lines,1):
        if current is None:current=new_session(number);sessions.append(current)
        if BOOT.search(line) and (observed(current) or current['identity_line']):current=new_session(number);sessions.append(current)
        version=VERSION.search(line)
        if version:
            family='CUSTOM_WEWIN' if 'wewin' in version[2].lower() else 'UNATTRIBUTED'
            if (not current['identity_line'] and observed(current)) or (current['identity_line'] and (current['numeric_app_version']!=version[1] or current['build_family']!=family)):
                current=new_session(number);sessions.append(current)
            current.update(numeric_app_version=version[1],build_family=family,identity_line=number)
        for marker in current['protocol_marker_lines']:
            if marker in line.lower():current['protocol_marker_lines'][marker].append(number)
        for event,pattern in EVENTS:
            if event.endswith('_connected') and re.search(r'not\s+connected|failed|error|disconnected',line,re.I):continue
            if re.search(pattern,line,re.I):current['events'].append({'line':number,'event':event})
        start=line.find('{')
        if start>=0:
            try:payload,_=json.JSONDecoder().raw_decode(line[start:])
            except ValueError:payload=None
            if isinstance(payload,dict) and payload.get('type')=='hello' and payload.get('transport') in ('udp','websocket'):
                safe={'line':number,'event':'logged_hello','declared_transport':payload['transport']}
                params=payload.get('audio_params') or {}
                if isinstance(params,dict):
                    for key,allowed in [('sample_rate',(16000,24000,48000)),('channels',(1,2)),('frame_duration',(20,40,60))]:
                        if type(params.get(key)) is int and params[key] in allowed:safe[key]=params[key]
                    if params.get('format')=='opus':safe['format']='opus'
                current['events'].append(safe)
        for endpoint in endpoint_facts(line):
            if not any(all(v.get(k)==endpoint[k] for k in ('scheme','host','port')) for v in current['endpoints']):current['endpoints'].append({'line':number,**endpoint})
    # Facts seen before a later version line remain time-local, never relabeled as
    # proven current hardware, even when one file contains multiple boot captures.
    return {'file':str(path.resolve()),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'line_count':len(lines),'sessions':sessions,'classification':'VERIFIED_FROM_SAVED_LOGS','current_robot_transport':'UNVERIFIED','serial_opened':False,'network_contacted':False,'raw_log_exported':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('logs',nargs='+',type=Path);parser.add_argument('--out',required=True,type=Path);args=parser.parse_args()
    root=Path(__file__).resolve().parents[1];out=args.out.resolve()
    if not out.is_relative_to(root/'artifacts'):raise ValueError('Write private evidence only inside artifacts/')
    result={'scope':'OFFLINE_SAVED_LOGS_ONLY','files':[inspect_log(p) for p in args.logs]}
    out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'files':len(result['files']),'events':sum(len(s['events']) for f in result['files'] for s in f['sessions']),'current_robot_transport':'UNVERIFIED','raw_logs_exported':False}))
