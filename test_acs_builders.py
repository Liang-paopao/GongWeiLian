import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class AcsBuilderTests(unittest.TestCase):
    def test_public_builder_rejects_example_root_domains(self):
        from scripts.build_platform_acs import build
        with tempfile.TemporaryDirectory() as folder:
            for host in ('example.com', 'example.org', 'example.net'):
                with self.subTest(host=host), self.assertRaisesRegex(ValueError, '示例'):
                    build(Path(folder), f'https://{host}')

    def test_public_builder_refuses_approved_directory_before_writes(self):
        from scripts.build_platform_acs import build, ACS_DIR
        with self.assertRaisesRegex(ValueError, '覆盖'):
            build(ACS_DIR, 'https://gongwei.yanyi.online')

    def test_all_drafts_preserve_approved_identities_and_endpoints(self):
        from scripts import build_agentic_acs_draft as builder
        current_dir = Path(__file__).parent / 'platform/approved_acs'
        with tempfile.TemporaryDirectory() as folder, patch.object(builder, 'TARGET', Path(folder)):
            builder.main()
            for name in ('leader', 'resource_partner', 'work_order_partner'):
                source = json.loads((current_dir / f'{name}.json').read_text(encoding='utf-8'))
                draft = json.loads((Path(folder) / f'{name}.json').read_text(encoding='utf-8'))
                self.assertEqual(draft['aic'], source['aic'])
                self.assertEqual(draft['endPoints'], source['endPoints'])
                self.assertEqual(draft['version'], '1.1.1' if name == 'leader' else '1.1.0')

    def test_leader_draft_matches_pipe_maintenance_requests(self):
        from scripts import build_agentic_acs_draft as builder
        with tempfile.TemporaryDirectory() as folder, patch.object(builder, 'TARGET', Path(folder)):
            builder.main()
            leader = json.loads((Path(folder) / 'leader.json').read_text(encoding='utf-8'))
        skill = next(item for item in leader['skills'] if item['id'] == 'gongwei.leader.pipe-maintenance')
        searchable = json.dumps(leader, ensure_ascii=False)
        self.assertIn('水管', searchable)
        self.assertIn('管道', searchable)
        self.assertIn('供水', searchable)
        self.assertIn('漏水', searchable)
        self.assertGreaterEqual(len(skill['examples']), 2)
        self.assertIn('检修', skill['tags'])

    def test_hybrid_uses_current_identity_and_does_not_mutate_approved_input(self):
        from scripts.build_hybrid_leader_acs import build, CURRENT_APPROVED
        original = CURRENT_APPROVED.read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / 'leader.json'
            build(output)
            card = json.loads(output.read_text(encoding='utf-8'))
            self.assertEqual(card['aic'], json.loads(original)['aic'])
            self.assertEqual(card['version'], '1.1.1')
            self.assertEqual(card['endPoints'][0]['url'], 'https://leader.yanyi.online/rpc')
            self.assertIn('text/plain', card['defaultInputModes'])
            self.assertIn('messageQueue', card['capabilities'])
        self.assertEqual(CURRENT_APPROVED.read_bytes(), original)

    def test_retired_identity_cannot_replace_current_leader(self):
        from scripts.build_hybrid_leader_acs import build, CURRENT_APPROVED
        card = json.loads(CURRENT_APPROVED.read_text(encoding='utf-8'))
        card['aic'] = 'retired-test-identity'
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / 'old.json'
            source.write_text(json.dumps(card), encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'AIC'):
                build(Path(folder) / 'output.json', approved_path=source)
            self.assertFalse((Path(folder) / 'output.json').exists())

    def test_explicit_https_routes_are_used_without_invented_paths(self):
        from scripts.build_platform_acs import build, ACS_DIR, AICS, CERT_VARS, ENDPOINT_VARS
        with tempfile.TemporaryDirectory() as folder:
            cert = Path(folder) / 'test-file'
            cert.write_text('fixture: configuration-path test only, not a certificate', encoding='utf-8')
            env = {name: str(cert) for name in CERT_VARS}
            env['GONGWEI_PUBLIC_BASE_URL'] = 'https://gongwei.yanyi.online'
            for filename, name in AICS.items():
                env[name] = json.loads((ACS_DIR / filename).read_text(encoding='utf-8'))['aic']
                env[ENDPOINT_VARS[filename]] = f'https://gongwei.yanyi.online/explicit-{filename}/rpc'
            with patch.dict(os.environ, env, clear=True):
                outputs = build(Path(folder) / 'out')
            self.assertEqual(len(outputs), 3)
            for output in outputs:
                card = json.loads(output.read_text(encoding='utf-8'))
                self.assertEqual(card['endPoints'][0]['url'], env[ENDPOINT_VARS[output.name]])
            del env[ENDPOINT_VARS['resource_partner.json']]
            with patch.dict(os.environ, env, clear=True):
                with self.assertRaisesRegex(ValueError, 'endpoint'):
                    build(Path(folder) / 'missing')
            self.assertFalse((Path(folder) / 'missing').exists())
