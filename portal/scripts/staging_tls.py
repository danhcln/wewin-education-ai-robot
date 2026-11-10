"""Private staging CA only. Never installs trust, contacts ACME or changes a robot.
Run generation/inspection with Portal .venv (cryptography already provisioned).
"""
import argparse
from datetime import datetime,timedelta,timezone
import ipaddress
import json
from pathlib import Path
from cryptography import x509
from cryptography.hazmat.primitives import hashes,serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID,ExtendedKeyUsageOID

ROOT=Path(__file__).resolve().parents[1]


def create(out,host):
    out=out.resolve();ip=ipaddress.ip_address(host)
    if not out.is_relative_to(ROOT/'artifacts') or out.exists():raise ValueError('Use a NEW private artifacts directory; never overwrite keys')
    if not ip.is_private or ip.is_unspecified or ip.is_multicast:raise ValueError('Staging certificate only for a local/private IP')
    out.mkdir(parents=True)
    now=datetime.now(timezone.utc);ca_key=rsa.generate_private_key(public_exponent=65537,key_size=3072)
    name=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'WeWIN staging test CA - NOT robot trust')])
    ca=(x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(ca_key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(minutes=5)).not_valid_after(now+timedelta(days=30)).add_extension(x509.BasicConstraints(ca=True,path_length=0),critical=True).add_extension(x509.KeyUsage(False,False,False,False,False,True,True,False,False),critical=True).sign(ca_key,hashes.SHA256()))
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    subject=x509.Name([x509.NameAttribute(NameOID.COMMON_NAME,'wewin-staging.invalid')])
    def leaf(expired=False):
        return (x509.CertificateBuilder().subject_name(subject).issuer_name(name).public_key(key.public_key()).serial_number(x509.random_serial_number()).not_valid_before(now-timedelta(days=2) if expired else now-timedelta(minutes=5)).not_valid_after(now-timedelta(days=1) if expired else now+timedelta(days=7)).add_extension(x509.BasicConstraints(ca=False,path_length=None),critical=True).add_extension(x509.SubjectAlternativeName([x509.IPAddress(ip),x509.DNSName('wewin-staging.invalid')]),critical=False).add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]),critical=False).add_extension(x509.KeyUsage(True,False,True,False,False,False,False,False,False),critical=True).sign(ca_key,hashes.SHA256()))
    cert=leaf()
    for name,value in [('ca.pem',ca),('server.pem',cert),('expired.pem',leaf(True))]:
        with (out/name).open('xb') as stream:stream.write(value.public_bytes(serialization.Encoding.PEM))
    # CA key is intentionally not persisted. Reissue means a new explicit test CA.
    with (out/'server-key.pem').open('xb') as stream:stream.write(key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.PKCS8,serialization.NoEncryption()))
    receipt={'scope':'STAGING_CA_ONLY_NOT_INSTALLED','ip_san':host,'dns_san':'wewin-staging.invalid','ca_sha256':ca.fingerprint(hashes.SHA256()).hex(),'leaf_sha256':cert.fingerprint(hashes.SHA256()).hex(),'valid_until_utc':cert.not_valid_after_utc.isoformat(),'robot_trust_verified':False,'ca_private_key_persisted':False}
    (out/'receipt.json').write_text(json.dumps(receipt,indent=2));return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--out',type=Path,required=True);parser.add_argument('--host',required=True);args=parser.parse_args();print(json.dumps(create(args.out,args.host)))
