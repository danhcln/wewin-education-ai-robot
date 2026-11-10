"""Domain-separated live descriptors; existing file signing is untouched."""
import re
import time
from urllib.parse import urlsplit
from src.media.audio_endpoint import lan_ipv4


def canonical(d, now=None):
    if not isinstance(d, dict) or set(d) != {'session_id','generation','stream_url','token','expires_at'}:
        raise ValueError('Invalid descriptor fields')
    if not re.fullmatch('[a-f0-9]{32}',d['session_id']) or not re.fullmatch('[a-f0-9]{64}',d['token']):
        raise ValueError('Invalid live authority')
    if type(d['generation']) is not int or not 1 <= d['generation'] <= 0x7fffffff or type(d['expires_at']) is not int:
        raise ValueError('Invalid counters')
    url=d['stream_url']
    if not isinstance(url,str) or not 1<=len(url)<=512 or not url.isascii() or any(ord(c)<=32 for c in url) or any(c in url for c in '%\\@?#'):
        raise ValueError('Invalid live URL')
    p=urlsplit(url)
    if p.scheme!='udp' or p.path!='/wewin-stream/live' or p.username or p.password or not p.port or not 1024<=p.port<=65535 or p.netloc!=f'{lan_ipv4(p.hostname)}:{p.port}':
        raise ValueError('Only literal, private LAN UDP origin and exact stream route')
    if now is not None and (now<1700000000 or not now<d['expires_at']<=now+300):
        raise ValueError('Expired or untrusted clock')
    return ('wewin-stream-v1\n'+d['session_id']+'\n'+str(d['generation'])+'\n'+url+'\n'+d['token']+'\n'+str(d['expires_at'])).encode('ascii')


def sign(d, key_file):
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec,utils
    payload=canonical(d,int(time.time()))
    key=serialization.load_pem_private_key(key_file.read_bytes(),password=None)
    if not isinstance(key,ec.EllipticCurvePrivateKey) or not isinstance(key.curve,ec.SECP256R1):
        raise ValueError('Dedicated audio P-256 authority required')
    r,s=utils.decode_dss_signature(key.sign(payload,ec.ECDSA(hashes.SHA256())))
    return {**d,'signature':(r.to_bytes(32,'big')+s.to_bytes(32,'big')).hex()}
