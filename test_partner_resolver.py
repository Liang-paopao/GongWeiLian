import tempfile
import unittest
from pathlib import Path

from partner_resolver import PartnerResolver
from stage2_db import initialize_database


class PartnerResolverTests(unittest.TestCase):
    def test_catalog_without_alive_map_is_explicit_and_has_unknown_liveness(self):
        import json
        import os
        from unittest.mock import patch
        acs = json.loads((Path(__file__).parent / 'platform/approved_acs/resource_partner.json').read_text(encoding='utf-8'))
        aic = acs['aic']
        response = {'result': {'acsMap': {aic: acs}, 'agents': [{'group': 'filtered', 'agentSkills': [{'aic': aic, 'skillId': 'gongwei.resource.query', 'ranking': 1}]}]}}
        class Response:
            def __enter__(self): return self
            def __exit__(self, *args): return False
            def read(self): return json.dumps(response).encode()
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {
            'GONGWEI_PARTNER_DISCOVERY_POLICY': 'platform_catalog',
            'GONGWEI_MQ_RESOURCE_AIC': aic,
        }):
            resolver = PartnerResolver(db_path=Path(root) / 'catalog.db', discovery_url='https://wt.ioa.pub/discovery', strict_online=True)
            with patch('partner_resolver.urllib.request.urlopen', return_value=Response()) as send:
                result = resolver.resolve('resource', ['gongwei.resource.query'])
            query = json.loads(send.call_args.args[0].data)
            self.assertIn('extFilter', query)
            self.assertEqual(result['source'], 'discovery_catalog')
            self.assertEqual(result['selected']['aic'], aic)
            self.assertFalse(result['selected']['online'])
            self.assertEqual(result['selected']['liveness'], 'unknown')

    def test_discovery_preserves_platform_alive_map_for_both_policies(self):
        import json
        import os
        from unittest.mock import patch

        acs = json.loads((Path(__file__).parent / 'platform/approved_acs/resource_partner.json').read_text(encoding='utf-8'))
        aic = acs['aic']
        for policy in ('default_online', 'platform_catalog'):
            for alive, expected in ((True, 'online'), (False, 'offline'), ('true', 'unknown'), (None, 'unknown')):
                with self.subTest(policy=policy, alive=alive):
                    response = {'result': {
                        'acsMap': {aic: acs},
                        'agents': [{'group': 'filtered', 'agentSkills': [{'aic': aic, 'skillId': 'gongwei.resource.query', 'ranking': 1}]}],
                        'aliveMap': {aic: {'alive': alive, 'aliveLastSeenAt': '2026-10-10T18:48:14.251Z'}},
                    }}

                    class Response:
                        def __enter__(self): return self
                        def __exit__(self, *args): return False
                        def read(self): return json.dumps(response).encode()

                    with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {
                        'GONGWEI_PARTNER_DISCOVERY_POLICY': policy,
                        'GONGWEI_MQ_RESOURCE_AIC': aic,
                    }):
                        resolver = PartnerResolver(db_path=Path(root) / 'resolver.db', discovery_url='https://wt.ioa.pub/discovery', strict_online=True)
                        with patch('partner_resolver.urllib.request.urlopen', return_value=Response()):
                            result = resolver.resolve('resource', ['gongwei.resource.query'])
                        self.assertEqual(result['selected']['online'], alive is True)
                        self.assertEqual(result['selected'].get('liveness'), expected)
                        self.assertEqual(result['selected'].get('aliveLastSeenAt'), '2026-10-10T18:48:14.251Z')

    def test_catalog_policy_requires_pinned_identity_and_does_not_retry(self):
        import os
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root, patch.dict(os.environ, {'GONGWEI_PARTNER_DISCOVERY_POLICY': 'platform_catalog'}, clear=True):
            resolver = PartnerResolver(db_path=Path(root) / 'catalog.db', discovery_url='https://wt.ioa.pub/discovery', strict_online=True)
            with patch('partner_resolver.urllib.request.urlopen') as send:
                result = resolver.resolve('resource', ['gongwei.resource.query'])
            self.assertIsNone(result['selected'])
            send.assert_not_called()

    def test_static_fallback_is_explicit_and_skill_filtered(self):
        with tempfile.TemporaryDirectory() as root:
            db = Path(root) / "resolver.db"
            initialize_database(db)
            resolver = PartnerResolver(db_path=db, discovery_url=None)
            result = resolver.resolve("resource", ["gongwei.resource.query"])
            self.assertEqual(result["source"], "static_fallback")
            self.assertTrue(result["selected"])
            self.assertTrue(all("gongwei.resource.query" in item["skills"] for item in result["candidates"]))

    def test_online_failure_is_not_silent(self):
        with tempfile.TemporaryDirectory() as root:
            resolver = PartnerResolver(db_path=Path(root) / "resolver.db", discovery_url="https://127.0.0.1:1/discovery")
            result = resolver.resolve("workorder", ["gongwei.work-order.create"])
            self.assertEqual(result["source"], "discovery_failed")
            self.assertFalse(result["selected"])

    def test_online_http_error_preserves_status_for_acceptance_report(self):
        import urllib.error
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as root:
            resolver = PartnerResolver(db_path=Path(root) / "resolver.db", discovery_url="https://wt.ioa.pub/discovery")
            error = urllib.error.HTTPError("https://wt.ioa.pub/discovery/discover", 404, "Not Found", {}, None)
            with patch("partner_resolver.urllib.request.urlopen", side_effect=error):
                result = resolver.resolve("resource", ["gongwei.resource.query"])
            self.assertEqual(result["http_status"], 404)
            self.assertIn("404", result["error"])

    def test_online_query_uses_official_acps_adp_v2_path(self):
        from unittest.mock import patch

        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                return False
            def read(self):
                return b'{"result":{"acsMap":{},"agents":[]}}'

        with tempfile.TemporaryDirectory() as root:
            resolver = PartnerResolver(db_path=Path(root) / "resolver.db", discovery_url="https://wt.ioa.pub/discovery")
            with patch("partner_resolver.urllib.request.urlopen", return_value=Response()) as request:
                resolver.resolve("resource", ["gongwei.resource.query"])
            self.assertIn("/discovery/acps-adp-v2/discover", request.call_args.args[0].full_url)

    def test_capability_lookup_is_filtered_and_binds_configured_identity(self):
        import json
        import os
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root:
            resolver = PartnerResolver(db_path=Path(root) / 'resolver.db', discovery_url='https://wt.ioa.pub/discovery', strict_online=True)
            with patch.dict(os.environ, {'GONGWEI_MQ_RESOURCE_AIC': 'expected-resource'}), patch('partner_resolver.urllib.request.urlopen', side_effect=RuntimeError('capture')) as send:
                resolver.resolve('resource', ['gongwei.resource.query'])
            payload = json.loads(send.call_args.args[0].data)
            self.assertEqual(payload['type'], 'filtered')
            self.assertIn({'field': 'aic', 'op': 'eq', 'value': 'expected-resource'}, payload['filter']['conditions'])
            self.assertIn({'field': 'skills.id', 'op': 'eq', 'value': 'gongwei.resource.query'}, payload['filter']['conditions'])

    def test_online_mismatched_identity_cannot_be_selected(self):
        import os
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as root:
            resolver = PartnerResolver(db_path=Path(root) / 'resolver.db', discovery_url='https://wt.ioa.pub/discovery', strict_online=True)
            candidate = resolver._static('resource')[0]
            candidate['aic'] = 'other-resource'
            candidate['online'] = True
            with patch.dict(os.environ, {'GONGWEI_MQ_RESOURCE_AIC': 'expected-resource'}), patch.object(resolver, '_online', return_value=[candidate]):
                result = resolver.resolve('resource', ['gongwei.resource.query'])
            self.assertIsNone(result['selected'])
            self.assertEqual(result['filtered'][0]['reason'], 'configured_identity_mismatch')


if __name__ == "__main__":
    unittest.main()
