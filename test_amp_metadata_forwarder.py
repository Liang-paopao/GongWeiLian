"""Offline tests use real SDK records and temporary files; no broker contact."""
import asyncio
import hashlib
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
import uuid
from unittest.mock import AsyncMock, patch

from acps_sdk.amp import (AccessBody, AccessEmitter, AccessParticipant, AccessRequest,
                         AccessResponse, MessageBody, MessageDestination, MessageEmitter)

AICS = {
    'leader': '1.2.156.3088.1.BUPT.JSQB3Y.GD6IGY.AWF688.0WV9',
    'resource-inbox': '1.2.156.3088.1.BUPT.JSQB3Y.E164E8.FWIZ4R.03IA',
    'workorder-inbox': '1.2.156.3088.1.BUPT.JSQB3Y.Q9QG7Q.14TNDP.0WSF',
}


def module(case):
    case.assertIsNotNone(importlib.util.find_spec('amp_metadata_forwarder'),
                         'The restricted protocol metadata forwarder is missing')
    import amp_metadata_forwarder
    return amp_metadata_forwarder


def config():
    return {'broker': 'wt.ioa.pub:19092',
            'sources': [{'role': role, 'aic': aic} for role, aic in AICS.items()]}


class MetadataForwarderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.m = module(self)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.ack = SimpleNamespace(partition=1, offset=23)
        self.send = AsyncMock(return_value=self.ack)
        self.events = []
        self.forwarders = []
        self.forwarder = self.new_forwarder()
        self.sources = self.forwarder.sources
        self.access = next(s for s in self.sources if s['log_type'] == 'access')
        self.message = next(s for s in self.sources if s['log_type'] == 'message' and s['role'] == 'leader')

    def new_forwarder(self, **kwargs):
        forwarder = self.m.MetadataForwarder(config=config(), send=self.send,
            state_dir=self.root / 'state', test_log_root=self.root / 'logs',
            test_owner_ids={role: (os.stat(self.root).st_uid, os.stat(self.root).st_gid) for role in AICS},
            report=self.events.append, **kwargs)
        self.forwarders.append(forwarder)
        self.addCleanup(forwarder.close)
        return forwarder

    def write_access(self, source=None, task='task-1'):
        source = source or self.access
        emitter = AccessEmitter(source['log_path'], aic=source['aic'])
        emitter.emit_sync(AccessBody(durationMs=1.5,
            request=AccessRequest(method='start', url='/rpc', route='/rpc'),
            response=AccessResponse(statusCode=200),
            caller=AccessParticipant(aic=AICS['resource-inbox']),
            callee=AccessParticipant(aic=source['aic'], serviceName='gongwei-leader_rpc')),
            correlation_id=task)
        return source['log_path'].read_bytes().splitlines()[-1]

    def write_message(self, source=None):
        source = source or self.message
        emitter = MessageEmitter(source['log_path'], aic=source['aic'])
        emitter.emit_sync(MessageBody(eventType='send', operationName='publish', system='rabbitmq',
            destination=MessageDestination(name='group-1.exchange', kind='exchange', virtualHost='/acps'),
            messageId='message-1', payloadSizeBytes=120,
            attributes={'taskId': 'task-1', 'msgType': 'task-command'}), correlation_id='task-1')
        return source['log_path'].read_bytes().splitlines()[-1]

    async def restart(self):
        self.forwarder.close()
        self.forwarder = self.new_forwarder()

    async def test_exact_real_sdk_files_forward_unchanged_only_after_ack(self):
        access = self.write_access()
        message = self.write_message()
        await self.forwarder.poll_once()
        await self.forwarder.poll_once()
        self.assertEqual(self.send.await_count, 2)
        self.send.assert_any_await('access', AICS['leader'], access)
        self.send.assert_any_await('message', AICS['leader'], message)
        self.assertEqual({e['log_type'] for e in self.events}, {'access', 'message'})
        self.assertTrue(all(set(e) == {'log_type', 'log_id', 'aic', 'partition', 'offset'} for e in self.events))

    async def test_actual_partner_mq_filename_is_in_whitelist(self):
        for source in self.sources:
            if source['role'] != 'leader':
                digest = hashlib.sha256(source['aic'].encode()).hexdigest()
                self.assertEqual(source['log_path'].name, f'amp_message_partner_mq_{digest}.jsonl')
                self.write_message(source)
        await self.forwarder.poll_once()
        self.assertEqual(self.send.await_count, 2)

    async def test_network_failure_and_missing_ack_leave_cursor_unchanged(self):
        raw = self.write_access()
        self.send.side_effect = [ConnectionError('secret body must not print'), None, self.ack]
        for _ in range(3):
            await self.forwarder.poll_once()
        self.assertEqual(self.send.await_count, 3)
        self.assertEqual(self.send.await_args.args[2], raw)
        self.assertEqual(len(self.events), 1)
        self.assertNotIn('secret', json.dumps(self.events))

    async def test_invalid_ack_coordinates_never_advance(self):
        self.write_access()
        self.send.side_effect = [SimpleNamespace(partition=True, offset=2),
            SimpleNamespace(partition=-1, offset=2), SimpleNamespace(partition=1, offset=True),
            SimpleNamespace(partition=1, offset=2**63), self.ack]
        for _ in range(4):
            await self.forwarder.poll_once()
            self.assertEqual(self.forwarder.state['cursors'], {})
            self.assertEqual(self.forwarder.state['ledger'], {})
        await self.forwarder.poll_once()
        self.assertEqual(self.send.await_count, 5)

    async def test_restart_keeps_acknowledged_cursor(self):
        self.write_access()
        await self.forwarder.poll_once()
        await self.restart()
        await self.forwarder.poll_once()
        self.assertEqual(self.send.await_count, 1)
        self.assertEqual(self.forwarder.state_path.stat().st_nlink, 1)
        if os.name != 'nt':
            self.assertEqual(self.forwarder.state_path.stat().st_mode & 0o777, 0o600)

    async def test_acknowledged_id_duplicate_is_suppressed_after_rotation_and_restart(self):
        raw = self.write_access()
        await self.forwarder.poll_once()
        self.access['log_path'].rename(self.access['log_path'].with_suffix('.old'))
        self.access['log_path'].write_bytes(raw + b'\n')
        await self.restart()
        await self.forwarder.poll_once()
        self.assertEqual(self.send.await_count, 1)

    async def test_rotation_and_copytruncate_with_longer_file_are_safe(self):
        self.write_access()
        await self.forwarder.poll_once()
        path = self.access['log_path']
        path.write_bytes(b'')
        second = self.write_access(task='task-2')
        third = self.write_access(task='task-3')
        await self.forwarder.poll_once()
        self.assertEqual(self.send.await_count, 3)
        self.assertEqual([c.args[2] for c in self.send.await_args_list][-2:], [second, third])

    async def test_copytruncate_during_ack_preserves_new_file_records(self):
        original = self.write_access()
        replacement = []
        async def replace_while_sending(*args):
            self.access['log_path'].write_bytes(b'')
            replacement.append(self.write_access(task='task-new-first'))
            replacement.append(self.write_access(task='task-new-second'))
            self.send.side_effect = None
            return self.ack
        self.send.side_effect = replace_while_sending
        await self.forwarder.poll_once()
        self.assertEqual(self.send.await_count, 1)
        await self.restart()
        await self.forwarder.poll_once()
        self.assertEqual([c.args[2] for c in self.send.await_args_list], [original, *replacement])

    async def test_role_specific_uid_and_gid_are_required(self):
        self.write_access()
        self.write_message(next(s for s in self.sources if s['role'] == 'resource-inbox'))
        uid, gid = self.forwarder.owner_ids['leader']
        self.forwarder.owner_ids['leader'] = (uid, gid + 1)
        await self.forwarder.poll_once()
        self.assertEqual(self.send.await_count, 1)
        self.assertEqual(self.send.await_args.args[1], AICS['resource-inbox'])

    async def test_dynamicuser_ownership_is_refreshed_between_polls(self):
        self.write_access()
        actual = {role: (os.stat(self.root).st_uid, os.stat(self.root).st_gid) for role in AICS}
        old = {role: (uid + 1, gid + 1) for role, (uid, gid) in actual.items()}
        self.forwarder.close()
        with patch.object(self.m, '_source_owner_ids', side_effect=[old, old, actual]):
            self.forwarder = self.m.MetadataForwarder(config=config(), send=self.send,
                state_dir=self.root / 'state', test_log_root=self.root / 'logs', report=self.events.append)
            self.addCleanup(self.forwarder.close)
            await self.forwarder.poll_once()
            self.send.assert_not_awaited()
            await self.forwarder.poll_once()
        self.send.assert_awaited_once()

    async def test_only_fixed_systemd_private_directory_is_allowed(self):
        raw = self.write_access()
        private = self.root / 'logs' / 'private' / 'gongwei-leader' / 'amp'
        private.mkdir(parents=True)
        actual = private / self.access['log_path'].name
        actual.write_bytes(raw + b'\n')
        original_resolve = Path.resolve
        def resolve(path, *args, **kwargs):
            if path == self.access['log_path'].parent:
                return private
            return original_resolve(path, *args, **kwargs)
        with patch.object(Path, 'resolve', resolve):
            await self.forwarder.poll_once()
        self.send.assert_awaited_once_with('access', AICS['leader'], raw)
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / actual.name).write_bytes(raw + b'\n')
        def outside_resolve(path, *args, **kwargs):
            if path == self.access['log_path'].parent:
                return outside
            return original_resolve(path, *args, **kwargs)
        self.send.reset_mock()
        with patch.object(Path, 'resolve', outside_resolve):
            await self.forwarder.poll_once()
        self.send.assert_not_awaited()

    async def test_source_leaf_symlink_and_state_hardlink_are_rejected(self):
        raw = self.write_access()
        path = self.access['log_path']
        target = path.with_suffix('.real')
        path.rename(target)
        try:
            path.symlink_to(target)
        except OSError:
            # Windows CI often lacks the symlink privilege; test the same open
            # guard without changing production POSIX behavior.
            with patch.object(Path, 'is_symlink', lambda p: p == path):
                await self.forwarder.poll_once()
        else:
            await self.forwarder.poll_once()
            path.unlink()
        self.send.assert_not_awaited()
        path.write_bytes(raw + b'\n')
        await self.forwarder.poll_once()
        self.forwarder.close()
        os.link(self.forwarder.state_path, self.root / 'state-copy')
        with self.assertRaises(ValueError):
            self.new_forwarder()

    async def test_second_process_cannot_share_durable_state(self):
        with self.assertRaises(OSError):
            self.new_forwarder()

    async def test_partial_line_waits_until_newline(self):
        raw = self.write_access()
        self.access['log_path'].write_bytes(raw)
        await self.forwarder.poll_once()
        self.send.assert_not_awaited()
        with self.access['log_path'].open('ab') as handle:
            handle.write(b'\n')
        await self.forwarder.poll_once()
        self.send.assert_awaited_once()

    async def test_invalid_record_never_advances_or_leaks_payload(self):
        raw = self.write_access()
        record = json.loads(raw)
        record['body']['request']['headers'] = {'Authorization': 'SECRET'}
        self.access['log_path'].write_bytes(json.dumps(record).encode() + b'\n' + raw + b'\n')
        await self.forwarder.poll_once()
        self.send.assert_not_awaited()
        self.assertEqual(self.events, [])
        self.assertEqual(self.forwarder.state['cursors'], {})

    async def test_bounds_records_per_poll(self):
        self.forwarder.close()
        self.forwarder = self.new_forwarder(max_records=2)
        for i in range(3):
            self.write_access(task=f'task-{i}')
        await self.forwarder.poll_once()
        self.assertEqual(self.send.await_count, 2)
        await self.forwarder.poll_once()
        self.assertEqual(self.send.await_count, 3)

    async def test_rejects_hardlinked_wrong_owner_and_oversized_source(self):
        self.write_access()
        path = self.access['log_path']
        os.link(path, path.with_suffix('.hardlink'))
        await self.forwarder.poll_once()
        self.send.assert_not_awaited()
        path.with_suffix('.hardlink').unlink()
        uid, gid = self.forwarder.owner_ids['leader']
        self.forwarder.owner_ids['leader'] = (uid + 1, gid)
        await self.forwarder.poll_once()
        self.send.assert_not_awaited()
        self.forwarder.owner_ids['leader'] = (uid, gid)
        with patch.object(self.m, 'MAX_FILE_BYTES', 4):
            await self.forwarder.poll_once()
        self.send.assert_not_awaited()

    async def test_state_write_failure_blocks_further_records_and_retries(self):
        self.write_access()
        self.write_access(task='task-2')
        with patch.object(self.forwarder, '_persist', side_effect=OSError('private raw data')):
            await self.forwarder.poll_once()
        self.assertEqual(self.send.await_count, 1)
        self.assertEqual(self.events, [])
        self.assertEqual(self.forwarder.state['ledger'], {})
        await self.forwarder.poll_once()
        self.assertEqual(self.send.await_count, 3)

    async def test_duplicate_log_id_with_different_content_is_rejected(self):
        raw = self.write_access()
        await self.forwarder.poll_once()
        record = json.loads(raw)
        record['correlation_id'] = 'task-changed'
        with self.access['log_path'].open('ab') as handle:
            handle.write(json.dumps(record).encode() + b'\n')
        await self.forwarder.poll_once()
        self.assertEqual(self.send.await_count, 1)


class ValidationTests(unittest.TestCase):
    def setUp(self):
        self.m = module(self)

    def access(self):
        return {'schema_version': '1.0', 'log_type': 'access', 'log_id': str(uuid.uuid4()),
                'timestamp': '2026-10-09T02:00:00Z', 'aic': AICS['leader'],
                'correlation_id': 'task-1', 'body': {
                    'durationMs': 1, 'request': {'method': 'start', 'url': '/rpc', 'route': '/rpc'},
                    'response': {'statusCode': 200}, 'caller': {'aic': AICS['resource-inbox']},
                    'callee': {'aic': AICS['leader'], 'serviceName': 'gongwei-leader_rpc'}}}

    def validate(self, value):
        return self.m.validate_record(json.dumps(value).encode(), 'access', AICS['leader'])

    def message(self):
        value = self.access()
        value['log_type'] = 'message'
        value['body'] = {'eventType': 'receive', 'operationName': 'deliver', 'system': 'rabbitmq',
            'destination': {'name': 'group-1.member.queue', 'kind': 'queue', 'virtualHost': 'acps'},
            'messageId': 'message-1', 'subscriptionName': 'subscription-1', 'deliveryAttempt': 2,
            'payloadSizeBytes': 230, 'attributes': {'taskId': 'task-1', 'msgType': 'task-result'}}
        return value

    def validate_message(self, value):
        return self.m.validate_record(json.dumps(value).encode(), 'message', AICS['leader'])

    def test_message_recursive_whitelist_correlation_and_sdk_identifiers(self):
        self.validate_message(self.message())
        for path, key in [(('body',), 'payload'), (('body',), 'headers'),
                          (('body', 'destination'), 'arguments'),
                          (('body', 'attributes'), 'body'), (('body', 'attributes'), 'owner')]:
            value = self.message()
            node = value
            for name in path:
                node = node[name]
            node[key] = 'SECRET'
            with self.subTest(path=path, key=key), self.assertRaises(ValueError):
                self.validate_message(value)
        for name, new in [('taskId', 'wrong-task'), ('msgType', 'invitation')]:
            value = self.message(); value['body']['attributes'][name] = new
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.validate_message(value)
        value = self.message(); del value['correlation_id']
        with self.assertRaises(ValueError):
            self.validate_message(value)
        for field, new in [('messageId', ''), ('subscriptionName', 'secret topic'),
                           ('destination', {'name': 'https://example.test/SECRET'})]:
            value = self.message(); value['body'][field] = new
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate_message(value)

    def test_safe_numeric_metadata_and_only_settlement_latency_are_allowed(self):
        value = self.message()
        value['body']['eventType'], value['body']['operationName'] = 'ack', 'basic.ack'
        value['body']['settlement'] = {'latencyMs': 2.75}
        self.validate_message(value)
        for name, new in [('payloadSizeBytes', True), ('deliveryAttempt', 0),
                          ('settlement', {'latencyMs': 2, 'reason': 'SECRET'}),
                          ('settlement', {'latencyMs': -1})]:
            bad = json.loads(json.dumps(value)); bad['body'][name] = new
            with self.subTest(name=name, new=new), self.assertRaises(ValueError):
                self.validate_message(bad)
        value['body']['eventType'], value['body']['operationName'] = 'receive', 'deliver'
        with self.assertRaises(ValueError):
            self.validate_message(value)

    def test_ownership_lookup_uses_fixed_actual_service_names(self):
        import sys
        accounts = {'gongwei-leader': SimpleNamespace(pw_uid=62743, pw_gid=62743),
            'gongwei-resource-mq': SimpleNamespace(pw_uid=61798, pw_gid=61798),
            'gongwei-workorder-mq': SimpleNamespace(pw_uid=64816, pw_gid=64816)}
        lookup = unittest.mock.Mock(side_effect=accounts.__getitem__)
        with patch.object(self.m.os, 'name', 'posix'), patch.dict(sys.modules, {'pwd': SimpleNamespace(getpwnam=lookup)}):
            owners = self.m._source_owner_ids()
        self.assertEqual(owners['leader'], (62743, 62743))
        self.assertEqual({c.args[0] for c in lookup.call_args_list}, set(accounts))

    def test_config_requires_exact_official_endpoint_roles_and_current_identities(self):
        self.m.validate_config(config())
        for change in ({**config(), 'broker': 'other.example:19092'},
                       {**config(), 'broker': 'user:secret@wt.ioa.pub:19092'},
                       {**config(), 'sources': config()['sources'][:2]},
                       {**config(), 'state_dir': '/tmp'},
                       {**config(), 'sources': [{'role': 'leader', 'aic': 'aic'}] * 3}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.m.validate_config(change)
        sources = self.m.metadata_sources(config())
        self.assertEqual(len(sources), 4)
        self.assertTrue(all(s['log_path'].as_posix().startswith('/var/log/gongwei-') for s in sources))

    def test_recursive_unknown_or_body_fields_are_rejected(self):
        for path, key in [((), 'products'), ((), 'resource'), (('body',), 'text'),
                          (('body', 'request'), 'headers'), (('body', 'response'), 'headers'),
                          (('body', 'caller'), 'ip')]:
            value = self.access()
            node = value
            for name in path:
                node = node[name]
            node[key] = 'SECRET'
            with self.subTest(path=path, key=key), self.assertRaises(ValueError):
                self.validate(value)
        for key in ('message', 'stackTrace', 'data'):
            value = self.access()
            value['body']['error'] = {'code': 500, key: 'SECRET'}
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(value)

    def test_missing_identity_correlation_wrong_schema_and_native_types_are_rejected(self):
        changes = [('correlation_id', None), ('aic', AICS['resource-inbox']),
                   ('schema_version', '2.0'), ('timestamp', '2026-10-09T02:00:00')]
        for field, new in changes:
            value = self.access(); value[field] = new
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.validate(value)
        for bad in (None, {}, {'aic': 'caller'}, {'aic': AICS['resource-inbox'], 'serviceName': 'SECRET'}):
            value = self.access(); value['body']['caller'] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.validate(value)
        for bad in (True, '200', 700):
            value = self.access(); value['body']['response']['statusCode'] = bad
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                self.validate(value)

    def test_nonfinite_and_duplicate_json_are_rejected(self):
        with self.assertRaises(ValueError):
            self.m.validate_record(b'{"body": NaN}', 'access', AICS['leader'])
        with self.assertRaises(ValueError):
            self.m.validate_record(b'{"aic":"one","aic":"two"}', 'access', AICS['leader'])

    def test_cli_requires_explicit_plaintext_authorization(self):
        import contextlib
        import io
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            self.m.build_parser().parse_args(['--config', 'config.json'])
        args = self.m.build_parser().parse_args(['--config', 'config.json', '--public-protocol-metadata-plaintext'])
        self.assertTrue(args.public_protocol_metadata_plaintext)


class KafkaSenderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.m = module(self)
        self.options, self.calls, self.producers = [], [], []
        self.topics = {'amp.access', 'amp.message'}
        def factory(**options):
            self.options.append(options)
            metadata = SimpleNamespace(topics=lambda: self.topics)
            async def update(cluster_metadata, topics):
                self.calls.append(topics)
                return True
            client = SimpleNamespace(cluster=metadata, _metadata_update=update)
            async def start():
                await client._metadata_update(metadata, {'amp.access'})
            client.fetch_all_metadata = AsyncMock(return_value=metadata)
            producer = SimpleNamespace(client=client, start=AsyncMock(side_effect=start), stop=AsyncMock(),
                send_and_wait=AsyncMock(return_value=SimpleNamespace(topic='amp.access', partition=1, offset=2)))
            self.producers.append(producer)
            return producer
        self.sender = self.m.KafkaMetadataSender('wt.ioa.pub:19092', producer_factory=factory)
        self.addAsyncCleanup(self.sender.close)
        self.raw = json.dumps(ValidationTests.access(self)).encode()

    async def test_pinned_plaintext_all_topics_metadata_gate_and_real_ack(self):
        ack = await self.sender.send('access', AICS['leader'], self.raw)
        self.assertEqual(ack.offset, 2)
        self.assertEqual(self.calls, [[]])
        self.assertEqual(self.options[0]['acks'], 'all')
        self.assertEqual(self.options[0]['security_protocol'], 'PLAINTEXT')
        self.producers[0].send_and_wait.assert_awaited_once_with('amp.access', value=self.raw, key=AICS['leader'].encode())

    async def test_missing_topic_never_publishes_or_auto_creates(self):
        self.topics = {'amp.heartbeat'}
        with self.assertRaises(self.m.TopicUnavailable):
            await self.sender.send('access', AICS['leader'], self.raw)
        self.producers[0].send_and_wait.assert_not_awaited()
        self.producers[0].stop.assert_awaited_once()
        self.assertEqual(self.calls, [[]])

    async def test_sender_revalidates_before_any_connection(self):
        with self.assertRaises(ValueError):
            await self.sender.send('access', AICS['leader'], b'{"password":"SECRET"}')
        self.assertEqual(self.producers, [])

    async def test_sender_rejects_receipt_from_different_topic_and_retries_with_backoff(self):
        await self.sender.send('access', AICS['leader'], self.raw)
        self.producers[0].send_and_wait.return_value = SimpleNamespace(topic='amp.message', partition=1, offset=2)
        with self.assertRaises(ValueError):
            await self.sender.send('access', AICS['leader'], self.raw)
        self.producers[0].stop.assert_awaited_once()
        with self.assertRaises(self.m.RetryBackoff):
            await self.sender.send('access', AICS['leader'], self.raw)
        self.assertEqual(len(self.producers), 1)

    async def test_stop_bounds_loop_and_closes_every_resource(self):
        sender = SimpleNamespace(close=AsyncMock())
        forwarder = SimpleNamespace(poll_once=AsyncMock(), close=unittest.mock.Mock())
        await asyncio.wait_for(self.m.run_forwarder(forwarder, sender, asyncio.Event(), max_seconds=0.01), 1)
        sender.close.assert_awaited_once()
        forwarder.close.assert_called_once()


if __name__ == '__main__':
    unittest.main()
