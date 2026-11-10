"""Offline evidence only. Never reads NVS, contacts Cloud or opens a serial port.

Allowlisted app strings prove compiled capabilities, not current configuration or
reachable control flow. No arbitrary printable strings or credentials are saved.
"""
import argparse
import hashlib
import json
from pathlib import Path
import struct
import re
import zlib

MARKERS=(
    'https://xiaozhi-api.tandev282.workers.dev/ota',
    'wss://api.tenclass.net/xiaozhi/v1/',
    'ota_url','websocket','mqtt','Activation-Version','Authorization','Device-Id',
    'Client-Id','Serial-Number','Protocol-Version','audio_params','frame_duration',
    'sample_rate','opus','transport','udp','session_id','sentence_start','tools/list',
    'tools/call','initialize','notifications/initialized','challenge',
    'Connecting to websocket server','No mqtt section found',
    'No websocket section found','Unsupported transport','Received goodbye message',
    'keepalive','keep_alive_interval','aes-128-ctr','aes_ctr','/get_config','/submit',
    'enable_ota','Custom OTA URL','OTA URL','Hi, Lily','BtBridge','speaker.bluetooth',
)


def inspect(path):
    with path.open('rb') as source:
        # Partition table is public structural metadata; skip NVS entirely.
        source.seek(0x8000);table=source.read(0x1000)
        source.seek(0x20000);app=source.read(0x540000)
    if app[0]!=0xe9:raise ValueError('Expected ESP app image at factory ota0 offset')
    partitions=[]
    for i in range(0,len(table),32):
        magic,kind,subtype,offset,size,label,flags=struct.unpack('<HBBII16sI',table[i:i+32])
        if magic!=0x50aa:break
        partitions.append({'type':kind,'subtype':subtype,'offset':hex(offset),'size':hex(size),'label':label.split(b'\0')[0].decode('ascii','replace')})
    cursor=24;segments=[]
    for _ in range(app[1]):
        address,size=struct.unpack_from('<II',app,cursor);cursor+=8
        if size>len(app)-cursor:raise ValueError('Invalid ESP image segment')
        segments.append({'address':hex(address),'size':size,'file_offset':hex(0x20000+cursor)})
        cursor+=size
    checksum_end=(cursor+16)&~15
    image_size=checksum_end+(32 if app[23] else 0)
    app=app[:image_size]
    embedded_hash_valid=not app[23] or hashlib.sha256(app[:-32]).digest()==app[-32:]
    matches=[]
    for marker in MARKERS:
        needle=marker.encode();start=0;offsets=[]
        while (position:=app.find(needle,start))>=0:
            offsets.append(hex(0x20000+position));start=position+len(needle)
        matches.append({'marker':marker,'file_offsets':offsets})
    embedded=[]
    # Some factory provisioning pages are plaintext in DROM, not gzip.
    for match in re.finditer(b'<!doctype html',app.lower()):
        end=app.lower().find(b'</html>',match.start())
        if end<0:continue
        html=app[match.start():end+7]
        if b'ota_url' not in html:continue
        embedded.append({'file_offset':hex(0x20000+match.start()),'encoding':'plaintext','bytes':len(html),
                         'sha256':hashlib.sha256(html).hexdigest(),
                         'compiled_routes':[route for route in ('/advanced/config','/advanced/submit','/submit','/reboot') if route.encode() in html],
                         'advanced_payload_contains_ota_url':b'ota_url:document.getElementById("ota_url").value' in html,
                         'visibility_condition':'show_ota_config' if b'style.display=t.show_ota_config?' in html else 'unknown',
                         'runtime_visibility':'UNKNOWN','handler_execution':'NOT_RUN'})
    start=0
    while (position:=app.find(b'\x1f\x8b\x08',start))>=0:
        start=position+3
        try:
            data=zlib.decompressobj(16+zlib.MAX_WBITS).decompress(app[position:],2_000_000)
            if b'<html' in data.lower() or b'<!doctype' in data.lower():
                embedded.append({'file_offset':hex(0x20000+position),'decompressed_bytes':len(data),'markers':[m for m in MARKERS if m.encode() in data]})
        except zlib.error:pass
    first=32
    desc={}
    if struct.unpack_from('<I',app,first)[0]==0xabcd5432:
        for name,offset,size in [('version',16,32),('project',48,32),('idf',112,32)]:
            desc[name]=app[first+offset:first+offset+size].split(b'\0')[0].decode('ascii','replace')
    return {'classification':'OFFLINE_FACTORY_APP_ONLY_NOT_CURRENT_RUNTIME','path':str(path),
            'app_offset':'0x20000','app_size':image_size,'app_sha256':hashlib.sha256(app).hexdigest(),
            'embedded_sha256_valid':embedded_hash_valid,'description':desc,'partitions':partitions,'segments':segments,'allowlisted_markers':matches,
            'embedded_html':embedded,'nvs_read':False,'physical_probe':False,
            'limitations':'String presence is not proof of protocol selection, activation flow, supported UI or current firmware/endpoint.'}


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--backup',type=Path,default=Path('E:/WEWIN_IT/MonsterDesk_Backup/monster_desk_original_1.bin'));parser.add_argument('--out',type=Path,default=Path('artifacts/connection-preflight/factory.json'))
    args=parser.parse_args();result=inspect(args.backup);args.out.parent.mkdir(parents=True,exist_ok=True);args.out.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'app_sha256':result['app_sha256'],'description':result['description'],'present_markers':[m['marker'] for m in result['allowlisted_markers'] if m['file_offsets']],'embedded_html':result['embedded_html']}))
