"""Controlled local TLS chain/SNI diagnostics; never contacts a robot or Cloud.

One ephemeral 127.0.0.1 listener and one verified client connection. Does not
disable validation, alter AV/trust stores or add a CA to Windows. Private keys
are temporary; output contains only public certificate metadata and verdicts.
"""
import asyncio
import hashlib
import json
from pathlib import Path
import ssl
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from ai_server.mqtt_udp import server_tls_context

HOSTNAME = 'gateway.wewin-staging.invalid'


def certificate_chain(message, tls13):
    """Parse Certificate handshake bytes, including before verification failure."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    if len(message) < 7 or message[0] != 11 or int.from_bytes(message[1:4], 'big') != len(message)-4:
        raise ValueError('Invalid Certificate handshake')
    pos = 4
    if tls13:
        pos += 1 + message[pos]
    if pos + 3 > len(message):raise ValueError('Truncated chain list')
    end = pos + 3 + int.from_bytes(message[pos:pos+3], 'big')
    pos += 3
    if end != len(message):raise ValueError('Invalid chain size')
    chain = []
    while pos < end:
        size = int.from_bytes(message[pos:pos+3], 'big');pos += 3
        if not size or pos + size > end:raise ValueError('Truncated certificate')
        cert = x509.load_der_x509_certificate(message[pos:pos+size]);pos += size
        try:
            san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
            names = {'dns': san.get_values_for_type(x509.DNSName), 'ip': [str(v) for v in san.get_values_for_type(x509.IPAddress)]}
        except x509.ExtensionNotFound:names = {'dns': [], 'ip': []}
        chain.append({'subject': cert.subject.rfc4514_string(), 'issuer': cert.issuer.rfc4514_string(),
                      'sha256': cert.fingerprint(hashes.SHA256()).hex(), 'san': names})
        if tls13:
            if pos + 2 > end:raise ValueError('Truncated certificate extensions')
            size = int.from_bytes(message[pos:pos+2], 'big');pos += 2 + size
            if pos > end:raise ValueError('Truncated certificate extensions')
    return chain


def make_chain(directory):
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec
    import ipaddress
    now = datetime.now(timezone.utc)
    keys = [ec.generate_private_key(ec.SECP256R1()) for _ in range(3)]
    names = [x509.Name([x509.NameAttribute(x509.NameOID.COMMON_NAME, n)]) for n in
             ('WeWIN temporary gate Root', 'WeWIN temporary gate Intermediate', HOSTNAME)]
    certs = []
    for i in range(3):
        ca = i < 2;parent = max(0, i-1)
        builder = (x509.CertificateBuilder().subject_name(names[i]).issuer_name(names[parent])
                   .public_key(keys[i].public_key()).serial_number(x509.random_serial_number())
                   .not_valid_before(now-timedelta(minutes=2)).not_valid_after(now+timedelta(hours=2))
                   .add_extension(x509.BasicConstraints(ca=ca, path_length=(1-i) if ca else None), critical=True)
                   .add_extension(x509.KeyUsage(digital_signature=True, key_encipherment=False, key_cert_sign=ca,
                                                crl_sign=ca, content_commitment=False, data_encipherment=False,
                                                key_agreement=False, encipher_only=False, decipher_only=False), critical=True)
                   .add_extension(x509.SubjectKeyIdentifier.from_public_key(keys[i].public_key()), critical=False)
                   .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(keys[parent].public_key()), critical=False))
        if not ca:
            builder = builder.add_extension(x509.SubjectAlternativeName([x509.DNSName(HOSTNAME), x509.IPAddress(ipaddress.ip_address('127.0.0.1'))]), critical=False)
            builder = builder.add_extension(x509.ExtendedKeyUsage([x509.ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
        certs.append(builder.sign(keys[parent], hashes.SHA256()))
    root, full, leaf, key = [directory/name for name in ('root.pem', 'chain.pem', 'leaf.pem', 'key.pem')]
    pem = [cert.public_bytes(serialization.Encoding.PEM) for cert in certs]
    root.write_bytes(pem[0]);full.write_bytes(pem[2]+pem[1]);leaf.write_bytes(pem[2])
    key.write_bytes(keys[2].private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    return {'root':root,'chain':full,'leaf':leaf,'key':key,
            'expected_leaf_sha256':certs[2].fingerprint(hashes.SHA256()).hex()}


def client_context(files, trusted=True):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    if trusted:context.load_verify_locations(cafile=str(files['root']))
    assert context.check_hostname and context.verify_mode == ssl.CERT_REQUIRED
    return context


def engine_case(files, hostname=HOSTNAME, trusted=True, complete=True, tls12=False):
    server = server_tls_context(str(files['chain' if complete else 'leaf']), str(files['key']))
    seen = [];server.set_servername_callback(lambda socket, name, ctx: seen.append(name))
    context = client_context(files, trusted)
    if tls12:context.maximum_version = ssl.TLSVersion.TLSv1_2
    ci, co, si, so = [ssl.MemoryBIO() for _ in range(4)]
    client = context.wrap_bio(ci, co, server_hostname=hostname)
    peer = server.wrap_bio(si, so, server_side=True)
    try:
        for _ in range(16):
            for endpoint in (client, peer):
                try:endpoint.do_handshake()
                except ssl.SSLWantReadError:pass
            si.write(co.read());ci.write(so.read())
        leaf = hashlib.sha256(client.getpeercert(binary_form=True)).hexdigest()
        assert leaf == files['expected_leaf_sha256']
        client.write(b'wewin-controlled-tls');si.write(co.read())
        assert peer.read() == b'wewin-controlled-tls'
        return {'accepted':True,'version':client.version(),'sni':seen,'leaf_sha256':leaf}
    except ssl.SSLCertVerificationError as exc:
        return {'accepted':False,'verify_code':exc.verify_code,'verify_message':exc.verify_message,'sni':seen}


def engine_gate(files):
    cases = []
    for name, kwargs, expected in (
        ('complete_chain_dns_sni', {}, True), ('complete_chain_tls12', {'tls12':True}, True),
        ('ip_san_without_dns_sni', {'hostname':'127.0.0.1'}, True),
        ('wrong_hostname_rejected', {'hostname':'wrong.wewin-staging.invalid'}, False),
        ('unknown_ca_rejected', {'trusted':False}, False),
        ('missing_intermediate_rejected', {'complete':False}, False)):
        outcome = engine_case(files, **kwargs)
        assert outcome['accepted'] == expected, name
        if expected:assert outcome['sni'] == ([None] if kwargs.get('hostname')=='127.0.0.1' else [HOSTNAME])
        cases.append({'case':name,'result':'PASS',**outcome})
    return cases


async def network_gate(files):
    # The hostname is sent as SNI; connection itself is strictly numeric loopback.
    observed = [];seen_sni = [];writers = set()
    context = server_tls_context(str(files['chain']), str(files['key']))
    context.set_servername_callback(lambda socket, name, ctx: seen_sni.append(name))
    async def handle(reader, writer):
        writers.add(writer)
        try:
            writer.write(b'wewin-local-chain-gate');await writer.drain()
            await asyncio.wait_for(reader.read(1), 2)
        finally:
            writer.close()
            try:await writer.wait_closed()
            except (OSError, ssl.SSLError):pass
            writers.discard(writer)
    server = await asyncio.start_server(handle, '127.0.0.1', 0, ssl=context, ssl_handshake_timeout=2)
    client = client_context(files)
    def trace(conn, direction, version, kind, msg, data):
        if direction=='read' and int(msg)==11:
            observed.extend(certificate_chain(data, version==ssl.TLSVersion.TLSv1_3))
    client._msg_callback = trace
    result = {'target':'127.0.0.1 ephemeral only','requested_sni':HOSTNAME,
              'expected_leaf_sha256':files['expected_leaf_sha256'],'validation_enabled':True}
    writer = None
    try:
        reader, writer = await asyncio.wait_for(asyncio.open_connection('127.0.0.1',server.sockets[0].getsockname()[1],ssl=client,server_hostname=HOSTNAME), 5)
        channel = writer.get_extra_info('ssl_object')
        actual = hashlib.sha256(channel.getpeercert(binary_form=True)).hexdigest()
        if actual != files['expected_leaf_sha256']:raise ValueError('Unexpected verified leaf')
        assert await asyncio.wait_for(reader.readexactly(22), 2) == b'wewin-local-chain-gate'
        result.update(status='STAGING_VERIFIED',version=channel.version(),cipher=channel.cipher()[0],leaf_matches=True)
    except ssl.SSLCertVerificationError as exc:
        intercepted = any('Avast Web/Mail Shield' in cert['issuer'] for cert in observed)
        result.update(status='BLOCKED_INTERCEPTION' if intercepted else 'FAIL',verify_code=exc.verify_code,
                      verify_message=exc.verify_message,leaf_matches=False)
    except (OSError, ValueError, asyncio.TimeoutError) as exc:
        result.update(status='BLOCKED',error_type=type(exc).__name__)
    finally:
        if writer:
            writer.close();await writer.wait_closed()
        await asyncio.sleep(.05)
        server.close();await server.wait_closed()
        for peer in list(writers):peer.close()
        result.update(observed_chain=observed,server_observed_sni=seen_sni,
                      chain_evidence='certificates presented on handshake, not proof of trust or complete root chain on failure')
    return result


def main():
    output = ROOT/'artifacts/tandev-final-gate';output.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='wewin-final-tls-') as folder:
        files = make_chain(Path(folder))
        result = {'engine_cases':engine_gate(files),'network':asyncio.run(network_gate(files)),
                  'ca_installed':False,'validation_disabled':False,'av_modified':False,
                  'robot_contacted':False,
                  'independent_network_tls':'NOT_RUN_CURRENT_HOST_DIAGNOSTIC_ONLY',
                  'firmware_trust':'UNVERIFIED','keys_preserved':False}
    (output/'tls-evidence.json').write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))
    return 0 if result['network']['status']=='STAGING_VERIFIED' else 2


if __name__=='__main__':raise SystemExit(main())
