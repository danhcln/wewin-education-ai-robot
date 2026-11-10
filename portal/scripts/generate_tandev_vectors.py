"""Generate public, synthetic golden packets using the CNG reference oracle.

Never imports WeWIN AudioCipher, uses a robot or executes an ESP image.
"""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def build(directory):
    compiler=shutil.which('gcc')
    if not compiler:raise RuntimeError('Existing host GCC required; no installation attempted')
    source=ROOT/'tests/reference/tandev_udp_cng.c'
    exe=directory/'tandev_udp_cng.exe'
    subprocess.run([compiler,'-std=c11','-O2','-Wall','-Wextra',str(source),'-lbcrypt','-o',str(exe)],check=True,capture_output=True,timeout=60)
    return exe


def call(exe,*args):
    return subprocess.check_output([str(exe),*map(str,args)],text=True,timeout=5).strip()


def call_many(exe,requests):
    lines=[' '.join(map(str,row)) for row in requests]
    result=subprocess.check_output([str(exe),'batch'],input='\n'.join(lines)+'\n',text=True,timeout=15).splitlines()
    if len(result)!=len(lines):raise ValueError('Oracle reply count mismatch')
    return result


def generate(exe):
    key='000102030405060708090a0b0c0d0e0f'
    nonce='01000000123456780000000000000000'
    # Code-3 CBR packet with three 20ms CELT silence frames (RFC 6716).
    # Frozen independently of WeWIN/FFmpeg's encoder; libopus validates it in tests.
    opus=bytes.fromhex('fb03fffefffefffe')
    rows=[]
    for name,size,stamp,seq in (('one_byte',1,60,1),('one_block',16,120,2),
                              ('partial_block',17,180,3),('endian_pattern',32,0x01020304,0x05060708),
                              ('zero_timestamp_seq1',32,0,1),('zero_timestamp_seq2',32,0,2),
                              ('zero_timestamp_seq3',32,0,3),('max_opus_payload',1275,600,10)):
        plain=bytes(size) if 'zero_timestamp' in name else bytes(i%256 for i in range(size))
        rows.append({'id':name,'timestamp':stamp,'sequence':seq,'plaintext':plain.hex()})
    rows.append({'id':'raw_opus_60ms','timestamp':60,'sequence':1,'plaintext':opus.hex(),
                 })
    requests=[('send',key,nonce,row['timestamp'],row['sequence'],row['plaintext']) for row in rows]
    for row,wire in zip(rows,call_many(exe,requests)):
        if wire.startswith('ERROR:'):raise ValueError('Oracle refused a test packet')
        row['packet']=wire
    source=ROOT/'tests/reference/tandev_udp_cng.c'
    return {'scope':'SYNTHETIC_PUBLIC_TEST_KEYS_NOT_TANDEV_RUNTIME_CAPTURE',
            'oracle':'Host C header + Windows CNG AES-ECB with mbedTLS-style big-endian CTR',
            'oracle_source_sha256_lf':hashlib.sha256(source.read_text(encoding='utf-8').encode()).hexdigest(),
            'reference_commit':'a73e9a7e266e3196d1368ba46c30bee0d81f0a64',
            'actual_factory_firmware_executed':False,'key':key,'nonce':nonce,'vectors':rows}


if __name__=='__main__':
    out=ROOT/'artifacts/tandev-final-gate';out.mkdir(parents=True,exist_ok=True)
    result=generate(build(out))
    target=ROOT/'tests/fixtures/tandev_udp_vectors.json';target.parent.mkdir(exist_ok=True)
    target.write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'vectors':len(result['vectors']),'fixture_sha256':hashlib.sha256(target.read_bytes()).hexdigest()}))
