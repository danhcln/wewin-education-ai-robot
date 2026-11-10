"""Approved A: local saved files + read-only registry. No network or serial APIs.
Exact IP/MAC correlation stays in memory; exports aliases/masks, never credentials.
"""
from contextlib import closing
from datetime import datetime,timedelta,timezone
import argparse
import ipaddress
import json
from pathlib import Path
import re
import sqlite3
from saved_robot_log_evidence import inspect_log

ROOT=Path(__file__).resolve().parents[1]
MAC=r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}'
IP=r'(?:\d{1,3}\.){3}\d{1,3}'


def identity_hints(path):
    meta=inspect_log(path);raw=Path(path).read_bytes()
    text=raw.decode('utf-16' if raw.startswith((b'\xff\xfe',b'\xfe\xff')) else 'utf-8-sig',errors='replace')
    facts=[];rejected_bt_mac_lines=[]
    for number,line in enumerate(text.splitlines(),1):
        session=next(s for s in reversed(meta['sessions']) if s['start_line']<=number)
        if re.search(r'BT RX|BT TX|BtBridge|bluetooth|paired',line,re.I):
            if re.search(MAC,line):rejected_bt_mac_lines.append(number)
            continue
        mac=re.search(r'\bmode\s*:\s*sta\s*\(\s*('+MAC+r')\s*\)',line,re.I)
        ip=re.search(r'\bsta ip:\s*('+IP+r')',line,re.I) or re.search(r'WifiStation:.*?Got IP:\s*('+IP+r')',line,re.I)
        if mac:facts.append({'kind':'station_mac','value':mac[1].lower(),'line':number,'build_family':session['build_family']})
        if ip:
            try:address=str(ipaddress.IPv4Address(ip[1]))
            except ValueError:continue
            facts.append({'kind':'station_ip','value':address,'line':number,'build_family':session['build_family']})
    return meta,facts,rejected_bt_mac_lines


def identifier_shape(value):
    if not value:return 'absent'
    if re.fullmatch(MAC,value):return 'MAC_SYNTAX_NOT_HARDWARE_PROOF'
    if re.fullmatch(r'[0-9a-fA-F]{32}',value):return 'OPAQUE_HEX32_NOT_MAC'
    return 'OTHER_OPAQUE_IDENTIFIER'


def summarize(logs,rows):
    records=[identity_hints(p) for p in logs]
    macs=sorted({f['value'] for _,facts,_ in records for f in facts if f['kind']=='station_mac'})
    ips=sorted({f['value'] for _,facts,_ in records for f in facts if f['kind']=='station_ip'}|{r['last_ip'] for r in rows if r.get('last_ip')})
    mac_alias={v:'M'+str(i+1) for i,v in enumerate(macs)};ip_alias={v:'H'+str(i+1) for i,v in enumerate(ips)}
    def safe_ip(value):
        if not value:return None
        try:a=ipaddress.ip_address(value)
        except ValueError:return {'alias':ip_alias[value],'mask':'NOT_IP'}
        return {'alias':ip_alias[value],'mask':'.'.join(value.split('.')[:3])+'.xxx' if a.version==4 and not a.is_loopback else 'LOOPBACK_OR_OTHER','current_robot_ip_verified':False}
    files=[]
    for meta,facts,rejected in records:
        safe=[]
        for f in facts:
            value=f['value'];safe.append({'kind':f['kind'],'alias':mac_alias[value] if f['kind']=='station_mac' else ip_alias[value],'mask':'**:**:**:**:'+':'.join(value.split(':')[-2:]) if f['kind']=='station_mac' else safe_ip(value)['mask'],'line':f['line'],'build_family':f['build_family']})
        files.append({'file':meta['file'],'sha256':meta['sha256'],'facts':safe,'excluded_bluetooth_mac_line_count':len(rejected),'protocol_evidence':meta['sessions'],'current_device_link':'UNVERIFIED'})
    registry=[]
    for n,r in enumerate(rows,1):
        matches=[{'file':Path(m['file']).name,'line':f['line'],'build_family':f['build_family']} for m,facts,_ in records for f in facts if f['kind']=='station_ip' and f['value']==r.get('last_ip')]
        stamp=r.get('observed_at');source=r.get('evidence_source');mapping=r.get('external_mapping_source')
        registry.append({'alias':'REG'+str(n),'pairing_state':r.get('pairing_state') if r.get('pairing_state') in ('active','revoked','pending','unpaired') else 'OTHER_OR_ABSENT','wire_id_shape':identifier_shape(r.get('wire_id')),'wire_id_repeated_single_character':bool(r.get('wire_id') and len(set(r['wire_id']))==1),'name_contains_monster_desk':bool(re.search(r'monster[ _-]*desk',r.get('name') or '',re.I)),'hardware_alias_present':bool(r.get('hardware_alias')),'external_device_id_shape':identifier_shape(r.get('external_device_id')),'external_mapping_source':mapping if mapping in ('unverified','operator_verified','provider_verified') else 'OTHER','external_verified_timestamp_present':bool(r.get('external_verified_at')),'last_ip':safe_ip(r.get('last_ip')),'observed_at_ict':datetime.fromtimestamp(stamp/1000,timezone(timedelta(hours=7))).isoformat() if stamp else None,'observation_source':source if source in ('lan_presence','test','fixture') else 'OTHER_OR_ABSENT','firmware_present':bool(r.get('firmware_version')),'build_id_present':bool(r.get('build_id')),'boot_id_present':bool(r.get('boot_id')),'historical_ip_matches':matches,'current_monster_desk_identity':'UNVERIFIED'})
    return {'scope':'APPROVED_A_OFFLINE_ONLY','logs':files,'registry':registry,'distinct_historical_station_macs':len(macs),'router_dhcp_flow_history':'UNVERIFIED_NOT_PROVIDED','label_or_current_status':'NOT_PROVIDED','current_monster_desk':{'ip':'UNVERIFIED','mac':'UNVERIFIED','device_id':'UNVERIFIED','transport':'UNVERIFIED'},'raw_ids_or_credentials_exported':False,'network_or_serial_used':False}


def load_registry(path):
    with closing(sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)) as db:
        db.execute('PRAGMA query_only=ON');db.row_factory=sqlite3.Row
        return [dict(r) for r in db.execute('SELECT r.name,r.wire_id,r.hardware_alias,r.pairing_state,r.external_device_id,r.external_mapping_source,r.external_verified_at,o.last_ip,o.observed_at,o.evidence_source,o.firmware_version,o.build_id,o.boot_id FROM robots r LEFT JOIN robot_observations o ON o.robot_id=r.id ORDER BY r.created_at,r.id')]


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);args=parser.parse_args()
    target=args.out.resolve()
    if not target.is_relative_to(ROOT/'artifacts'):raise ValueError('Private evidence must stay inside ignored artifacts')
    logs=[ROOT.parent/p for p in ('captured_boot.log','v4_boot_captured.log','robot_live_serial.log','passive_diagnosis.log')]
    result=summarize(logs,load_registry(ROOT.parent/'Wewin Connector/Wewin_AI_Connector/.secrets/browser-sessions.sqlite3'))
    target.parent.mkdir(parents=True,exist_ok=True);target.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'registry_candidates':len(result['registry']),'historical_station_mac_candidates':result['distinct_historical_station_macs'],'current_identity':'UNVERIFIED','network_or_serial_used':False}))
