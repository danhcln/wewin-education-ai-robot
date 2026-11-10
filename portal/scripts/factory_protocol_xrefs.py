"""Bounded offline app-only literal xrefs. No device/Cloud/serial operations.

Instruction xrefs do not prove a path executes on the current physical robot.
"""
import json
from pathlib import Path
import re
import struct
import subprocess
from factory_connection_evidence import inspect

ROOT=Path(__file__).resolve().parents[1]


if __name__=='__main__':
    backup=Path('E:/WEWIN_IT/MonsterDesk_Backup/monster_desk_original_1.bin');meta=inspect(backup)
    if meta['app_sha256']!='95f39d86990461a9b073105497cbcff0729de13c3e73f4ebf3416e7ee0e2a241':raise ValueError('Unrecognized factory image; review address assumptions first')
    with backup.open('rb') as stream:stream.seek(0x20000);app=stream.read(meta['app_size'])
    out=ROOT/'artifacts/staging-hardening/factory';out.mkdir(parents=True,exist_ok=True)
    segments=[(int(s['file_offset'],16)-0x20000,int(s['address'],16),s['size']) for s in meta['segments']]
    def address(offset):
        for start,addr,size in segments:
            if start<=offset<start+size:return addr+offset-start
    segment=next(s for s in segments if s[1]==0x42000020);start,base,size=segment
    code=out/'factory-code.bin';code.write_bytes(app[start:start+size])
    objdump=ROOT.parent/'idf-tools/tools/xtensa-esp-elf/esp-15.2.0_20251204/xtensa-esp-elf/bin/xtensa-esp32s3-elf-objdump.exe'
    result=subprocess.run([str(objdump),'-D','-b','binary','-m','xtensa',f'--adjust-vma={hex(base)}',str(code)],capture_output=True,check=True)
    lines=result.stdout.decode('utf-8','replace').splitlines();(out/'code-disassembly.txt').write_text('\n'.join(lines),encoding='utf-8')
    loads={}
    for index,line in enumerate(lines):
        match=re.search(r'l32r\s+[^,]+,\s*0x([0-9a-f]+)',line)
        if match:loads.setdefault(int(match[1],16),[]).append(index)
    markers=['show_ota_config','/advanced/config','/advanced/submit','ota_url','mqtt','websocket','Activation-Version','Authorization','No protocol specified','Connecting to MQTT','Connecting to websocket','Saved settings: ota_url']
    records=[]
    for marker in markers:
        for match in list(re.finditer(re.escape(marker.encode()),app))[:20]:
            location=match.start();addr=address(location)
            if addr is None:continue
            ptrs=[address(m.start()) for m in re.finditer(re.escape(struct.pack('<I',addr)),app)];ptrs=[p for p in ptrs if p]
            selected=[]
            for index in sorted({i for p in ptrs for i in loads.get(p,[])}):
                    line=lines[index]
                    lo=index
                    while lo>0 and index-lo<350 and 'entry' not in lines[lo]:lo-=1
                    hi=index+1
                    while hi<len(lines) and hi-index<220 and 'retw' not in lines[hi]:hi+=1
                    name=marker.replace('/','_').replace(':','_').replace(' ','_')+'-'+format(addr,'x')+'-'+str(index)+'.txt'
                    (out/name).write_text('\n'.join(lines[lo:hi+1]),encoding='utf-8')
                    selected.append({'instruction':line.strip(),'snippet':name})
            records.append({'marker':marker,'file_offset':hex(location+0x20000),'address':hex(addr),'literal_addresses':[hex(p) for p in ptrs],'xrefs':selected})
    (out/'xrefs.json').write_text(json.dumps({'classification':'OFFLINE_LITERAL_XREF_NOT_RUNTIME_PROOF','app':meta,'records':records},indent=2),encoding='utf-8')
    print(json.dumps([{'marker':m,'xref_count':sum(len(r['xrefs']) for r in records if r['marker']==m)} for m in markers]))
