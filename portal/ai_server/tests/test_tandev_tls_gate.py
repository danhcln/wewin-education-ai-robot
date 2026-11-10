"""Public certificate-message parsing tests; no sockets or trust-store changes."""
from pathlib import Path
import sys
import tempfile
from unittest import TestCase
from cryptography import x509
from cryptography.hazmat.primitives import serialization

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts'))
from tandev_tls_gate import certificate_chain, make_chain, HOSTNAME


class TLSCertificateEvidenceTests(TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.files=make_chain(Path(self.tmp.name))
        certs=x509.load_pem_x509_certificates(self.files['chain'].read_bytes())
        self.der=[c.public_bytes(serialization.Encoding.DER) for c in certs]

    def message(self,tls13):
        chain=b''.join(len(d).to_bytes(3,'big')+d+(b'\0\0' if tls13 else b'') for d in self.der)
        body=(b'\0' if tls13 else b'')+len(chain).to_bytes(3,'big')+chain
        return b'\x0b'+len(body).to_bytes(3,'big')+body

    def test_tls13_chain_fingerprint_san_and_issuer_are_public_evidence(self):
        chain=certificate_chain(self.message(True),True)
        self.assertEqual(len(chain),2)
        self.assertEqual(chain[0]['sha256'],self.files['expected_leaf_sha256'])
        self.assertEqual(chain[0]['san'],{'dns':[HOSTNAME],'ip':['127.0.0.1']})
        self.assertEqual(chain[0]['issuer'],chain[1]['subject'])

    def test_tls12_chain_uses_different_certificate_message_layout(self):
        self.assertEqual(certificate_chain(self.message(False),False),certificate_chain(self.message(True),True))

    def test_truncated_or_wrong_length_handshakes_are_rejected(self):
        good=self.message(True)
        for raw in (b'',b'\x0b\0\0',good[:-1],good+b'\0',b'\x0b\0\0\x03\xff\0\0'):
            with self.assertRaises(ValueError):certificate_chain(raw,True)
