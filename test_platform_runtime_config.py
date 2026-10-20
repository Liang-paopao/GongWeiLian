import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

from platform_runtime_config import configure_platform_environment


class PlatformIdentityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / 'certs/private').mkdir(parents=True)
        self.records = {
            '工维联核心业务 Leader': {'aic': 'test-leader', 'approval_status': 'APPROVED', 'is_active': True},
            '工维联资源协调 Partner': {'aic': 'test-resource', 'approval_status': 'APPROVED', 'is_active': True},
            '工维联工单处理 Partner': {'aic': 'test-workorder', 'approval_status': 'APPROVED', 'is_active': True},
        }
        self.save_records()
        self.issue('test-resource')
        self.env = patch.dict(os.environ, {'GONGWEI_SECRETS_DIR': str(self.root), 'GONGWEI_TRANSPORT_MODE': 'platform_mq_inbox'}, clear=True)
        self.env.start()
        self.addCleanup(self.env.stop)

    def save_records(self):
        (self.root / 'aics.json').write_text(json.dumps(self.records), encoding='utf-8')

    def issue(self, aic, usage=ExtendedKeyUsageOID.CLIENT_AUTH, expired=False):
        key = ec.generate_private_key(ec.SECP256R1())
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, aic)])
        now = datetime.now(timezone.utc)
        cert = (x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
                .public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(now - timedelta(days=2))
                .not_valid_after(now + timedelta(days=-1 if expired else 1))
                .add_extension(x509.ExtendedKeyUsage([usage]), critical=False)
                .sign(key, hashes.SHA256()))
        pem = cert.public_bytes(serialization.Encoding.PEM)
        (self.root / 'certs/resource_partner.crt').write_bytes(pem)
        (self.root / 'certs/trust-bundle.pem').write_bytes(pem)
        (self.root / 'certs/private/resource_partner.key').write_bytes(key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

    def test_external_secret_directory_and_explicit_auth_url_are_preserved(self):
        os.environ['MQ_AUTH_SERVICE_URL'] = 'https://mq.example.org/auth/'
        result = configure_platform_environment('resource')
        self.assertEqual(result['aic'], 'test-resource')
        self.assertEqual(os.environ['GONGWEI_MQ_AUTH_SERVICE_URL'], 'https://mq.example.org/auth/')
        self.assertTrue(Path(result['cert_file']).is_relative_to(self.root.resolve()))
        self.assertEqual(os.environ['MQ_INBOX'], 'inbox_test-resource')

    def test_default_group_api_uses_verified_direct_mtls_endpoint(self):
        configure_platform_environment('resource')
        self.assertEqual(os.environ['GONGWEI_MQ_AUTH_SERVICE_URL'], 'https://wt.ioa.pub:9007')

    def test_wrong_agent_certificate_is_rejected_before_environment_mutation(self):
        self.issue('test-leader')
        with self.assertRaisesRegex(RuntimeError, 'AIC'):
            configure_platform_environment('resource')
        self.assertNotIn('AGENT_AIC', os.environ)

    def test_systemd_flat_credentials_use_explicit_paths(self):
        flat = self.root / 'credentials'
        flat.mkdir()
        paths = {'GONGWEI_AICS_FILE': 'aics.json',
                 'MQ_CERT_FILE': 'certs/resource_partner.crt',
                 'MQ_KEY_FILE': 'certs/private/resource_partner.key',
                 'MQ_CA_FILE': 'certs/trust-bundle.pem'}
        for variable, source in paths.items():
            target = flat / ('identity_' + source.replace('/', '_'))
            target.write_bytes((self.root / source).read_bytes())
            os.environ[variable] = str(target)
        os.environ['GONGWEI_SECRETS_DIR'] = str(flat)
        result = configure_platform_environment('resource')
        self.assertEqual(result['aic'], 'test-resource')
        self.assertEqual(result['cert_file'], os.environ['MQ_CERT_FILE'])

    def test_missing_explicit_identity_does_not_fall_back_to_old_identity(self):
        os.environ['GONGWEI_AICS_FILE'] = str(self.root / 'missing.json')
        with self.assertRaisesRegex(RuntimeError, 'AIC|aics'):
            configure_platform_environment('resource')
        self.assertNotIn('AGENT_AIC', os.environ)

    def test_server_only_certificate_cannot_be_used_for_mq(self):
        self.issue('test-resource', ExtendedKeyUsageOID.SERVER_AUTH)
        with self.assertRaisesRegex(RuntimeError, 'clientAuth'):
            configure_platform_environment('resource')

    def test_expired_certificate_is_rejected(self):
        self.issue('test-resource', expired=True)
        with self.assertRaisesRegex(RuntimeError, '有效期'):
            configure_platform_environment('resource')

    def test_shared_agent_aic_is_rejected(self):
        self.records['工维联核心业务 Leader']['aic'] = 'test-resource'
        self.save_records()
        with self.assertRaisesRegex(RuntimeError, '共用'):
            configure_platform_environment('resource')

    def test_mismatched_private_key_is_rejected(self):
        old_key = (self.root / 'certs/private/resource_partner.key').read_bytes()
        self.issue('test-resource')
        (self.root / 'certs/private/resource_partner.key').write_bytes(old_key)
        with self.assertRaisesRegex(RuntimeError, '私钥'):
            configure_platform_environment('resource')

    def test_declared_wrong_identity_is_rejected(self):
        os.environ['AGENT_AIC'] = 'wrong-agent'
        with self.assertRaisesRegex(RuntimeError, 'AGENT_AIC'):
            configure_platform_environment('resource')

    def test_plaintext_broker_is_rejected(self):
        os.environ['MQ_BROKER_URL'] = 'amqp://wt.ioa.pub:5672'
        with self.assertRaisesRegex(RuntimeError, 'amqps'):
            configure_platform_environment('resource')


if __name__ == '__main__':
    unittest.main()
