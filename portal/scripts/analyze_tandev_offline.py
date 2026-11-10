"""Offline public image/partition metadata; never inspect NVS or execute firmware.

Hashes full input files as opaque bytes. Copies only the original app, partition
table and bootloader into ignored artifacts. All string output is allowlisted.
"""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import stat
import struct
import zlib

from factory_connection_evidence import inspect, MARKERS

ROOT = Path(__file__).resolve().parents[1]
BACKUP = Path('E:/WEWIN_IT/MonsterDesk_Backup')
OUT = ROOT/'artifacts/tandev-offline-forensics'


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as file:
        for chunk in iter(lambda: file.read(1024*1024), b''):
            h.update(chunk)
    return h.hexdigest()


def image(data):
    if len(data) < 24 or data[0] != 0xE9 or not 1 <= data[1] <= 16:
        return {'is_esp_image': False}
    pos, xor = 24, 0xEF
    segments = []
    for _ in range(data[1]):
        if pos+8 > len(data):
            raise ValueError('Truncated image segment header')
        address, length = struct.unpack_from('<II', data, pos)
        pos += 8
        if length > len(data)-pos:
            raise ValueError('Truncated image segment body')
        segments.append({'address': hex(address), 'offset': pos, 'size': length})
        for byte in data[pos:pos+length]:
            xor ^= byte
        pos += length
    footer = (pos+16) & ~15
    end = footer + (32 if data[23] else 0)
    if end > len(data):
        raise ValueError('Truncated image footer')
    desc = {}
    if len(data) >= 208 and struct.unpack_from('<I', data, 32)[0] == 0xABCD5432:
        for name, offset, length in (('version',16,32),('project',48,32),
                                     ('compile_time',80,16),('compile_date',96,16),('idf',112,32)):
            desc[name] = data[32+offset:32+offset+length].split(b'\0')[0].decode('ascii', 'replace')
        desc['elf_sha256'] = data[176:208].hex()
    return {'is_esp_image': True, 'image_size': end,
            'sha256': hashlib.sha256(data[:end]).hexdigest(),
            'checksum_valid': data[footer-1] == xor,
            'embedded_sha256_present': bool(data[23]),
            'embedded_sha256_valid': (hashlib.sha256(data[:footer]).digest()==data[footer:end]) if data[23] else None,
            'entry': hex(struct.unpack_from('<I',data,4)[0]),
            'chip_id': struct.unpack_from('<H',data,12)[0],
            'description': desc, 'segments': segments}


def otadata(data):
    states = {0:'NEW',1:'PENDING_VERIFY',2:'VALID',3:'INVALID',4:'ABORTED',0xFFFFFFFF:'UNDEFINED'}
    records=[]
    for offset in (0,4096):
        if len(data)<offset+32:
            raise ValueError('Truncated two-sector OTA metadata')
        seq=struct.unpack_from('<I',data,offset)[0]
        state,crc=struct.unpack_from('<II',data,offset+24)
        # ROM implementation complements its input and output, like zlib.
        computed=zlib.crc32(data[offset:offset+4],0xFFFFFFFF)
        records.append({'sector_offset':hex(offset),'sequence':seq,'state':states.get(state,'UNKNOWN'),
                        'crc_valid':crc==computed,'structurally_selectable':seq!=0xFFFFFFFF and state not in (3,4) and crc==computed,
                        'two_slot_candidate':('ota_'+str((seq-1)%2)) if seq not in (0,0xFFFFFFFF) else None})
    return {'entries':records,'runtime_slot':'UNVERIFIED_HISTORICAL_SNAPSHOT_ONLY'}


def safe_copy(path, data):
    if path.exists():
        if path.read_bytes()!=data:
            raise ValueError('Refuse to replace existing evidence copy')
    else:
        with path.open('xb') as file:
            file.write(data)
        path.chmod(stat.S_IREAD)


def main():
    OUT.mkdir(parents=True,exist_ok=True)
    inventory=[]
    for path in sorted(BACKUP.glob('*.bin')):
        entry={'path':str(path),'bytes':path.stat().st_size,'sha256':sha(path)}
        if path.name.startswith('otadata_'):
            entry['otadata']=otadata(path.read_bytes())
        elif path.name=='xiaozhi_v3_stable.bin':
            entry['image']=image(path.read_bytes())
            entry['attribution']='CUSTOM_OR_HISTORICAL_NOT_FACTORY_BY_FILENAME'
        inventory.append(entry)
    first=BACKUP/'monster_desk_original_1.bin'
    meta=inspect(first)
    assert meta['app_sha256']=='95f39d86990461a9b073105497cbcff0729de13c3e73f4ebf3416e7ee0e2a241'
    with first.open('rb') as file:
        file.seek(0);boot=file.read(0x8000)
        file.seek(0x8000);table=file.read(0x1000)
        file.seek(0xD000);ota=file.read(0x2000)
        file.seek(0x20000);app=file.read(meta['app_size'])
        file.seek(0x560000);slot1=file.read(0x540000)
    for name,data in (('factory-app.bin',app),('factory-bootloader.bin',boot),('partition-table.bin',table)):
        safe_copy(OUT/name,data)
    md5_at=next((i for i in range(0,len(table),32) if table[i:i+2]==b'\xeb\xeb'),None)
    marker_list=list(MARKERS)+['ISRG Root X1','ISRG Root X2','esp_crt_bundle_attach',
        'esp_crt_bundle','cert_pem','skip_cert_common_name_check','usb_serial_jtag',
        '/dev/usbserjtag','/dev/uart','esp_vfs_dev_uart','CONFIG_ESP_CONSOLE',
        'MqttProtocol','WebsocketProtocol','Current version:','Free heap:',
        'mqtts://','mqtt://','ws://','wss://','/xiaozhi/v1/','endpoint','publish_topic',
        'client_id','username','password','token','version','server_time','activation',
        'signature','hmac','sha256','aes','url','key','nonce','server','port','uuid']
    markers=[]
    for marker in dict.fromkeys(marker_list):
        hits=[];start=0
        while (p:=app.find(marker.encode(),start))>=0:
            hits.append(hex(p+0x20000));start=p+len(marker)
        markers.append({'literal':marker,'occurrences':len(hits),'first_offsets':hits[:12]})
    result={'scope':'OFFLINE_NO_DEVICE_NVS_OR_FIRMWARE_EXECUTION',
            'timestamp_utc':datetime.now(timezone.utc).isoformat(),'inventory':inventory,
            'factory_app':image(app),'factory_bootloader':image(boot),
            'backup_ota1':image(slot1),'backup_ota1_erased_ff':all(b==255 for b in slot1),
            'partitions':meta['partitions'],
            'partition_md5_valid':md5_at is not None and hashlib.md5(table[:md5_at]).digest()==table[md5_at+16:md5_at+32],
            'backup_otadata':otadata(ota),'allowlisted_literals':markers,
            'advanced_ui':meta['embedded_html'],'original_files_changed':False,
            'nvs_interpreted_or_exported':False,'runtime_transport':'UNVERIFIED',
            'analysis_copies':[{'path':str(OUT/name),'sha256':sha(OUT/name)}
                               for name in ('factory-app.bin','factory-bootloader.bin','partition-table.bin')]}
    (OUT/'analysis.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps({'inventory_files':len(inventory),'app':result['factory_app']['description'],
                      'app_hash_valid':result['factory_app']['embedded_sha256_valid'],
                      'partition_md5_valid':result['partition_md5_valid'],
                      'bootloader_checksum_valid':result['factory_bootloader'].get('checksum_valid'),
                      'backup_ota1_is_image':result['backup_ota1']['is_esp_image'],
                      'otadata':result['backup_otadata']}))


if __name__=='__main__':
    main()
