"""Restricted, opt-in transport of real SDK Access/Message metadata.

CLI: --config <JSON> --public-protocol-metadata-plaintext [--max-seconds N]
Config contains only broker=wt.ioa.pub:19092 and three sources with role/aic.
The four actual collector filenames are derived here, never supplied by a
caller. The restricted service reads DynamicUser-owned logs with
CAP_DAC_READ_SEARCH and StateDirectory=gongwei-amp-metadata, mode 0700.
State files are mode 0600. Only acknowledged log identity and Kafka coordinates
are printed; rejected data and transport exception text are never printed.

Delivery is at least once: a crash between broker ACK and local fsync can repeat
the same unchanged log_id. The bounded ACK ledger suppresses ordinary restarts,
rotation duplicates and repeated local IDs; it does not fabricate broker ACKs.
No business content, credential loading, topic creation or TLS fallback exists.
"""
from __future__ import annotations

import argparse
import asyncio
from contextlib import suppress
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import re
import signal
import stat
import time
import uuid
from datetime import datetime

from acps_sdk.aic import is_valid_aic_format
from acps_sdk.amp import AccessLogRecord, MessageLogRecord
from amp_heartbeat_forwarder import (
    RetryBackoff, TopicUnavailable, _all_topics_metadata_only, _decode,
    _positive_seconds, _report, _validate_broker,
)

BROKER = 'wt.ioa.pub:19092'
STATE_DIR = Path('/var/lib/gongwei-amp-metadata')
MAX_FILE_BYTES = 64 * 1024 * 1024
MAX_LINE_BYTES = 16 * 1024
MAX_STATE_BYTES = 4 * 1024 * 1024
MAX_LEDGER = 8192
CURRENT_AICS = {
    'leader': '1.2.156.3088.1.BUPT.JSQB3Y.GD6IGY.AWF688.0WV9',
    'resource-inbox': '1.2.156.3088.1.BUPT.JSQB3Y.E164E8.FWIZ4R.03IA',
    'workorder-inbox': '1.2.156.3088.1.BUPT.JSQB3Y.Q9QG7Q.14TNDP.0WSF',
}
COLLECTORS = {
    'leader': (('access', 'leader_rpc'), ('message', 'leader_mq')),
    'resource-inbox': (('message', 'partner_mq'),),
    'workorder-inbox': (('message', 'partner_mq'),),
}
SOURCE_USERS = {'leader': 'gongwei-leader', 'resource-inbox': 'gongwei-resource-mq',
                'workorder-inbox': 'gongwei-workorder-mq'}
TOPICS = {'access': 'amp.access', 'message': 'amp.message'}
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,255}\Z')
OPERATIONS = {'send': 'publish', 'receive': 'deliver', 'ack': 'basic.ack',
              'nack': 'basic.nack', 'reject': 'basic.reject',
              'timeout': 'basic.timeout', 'dead_letter': 'basic.dead_letter'}


def _keys(value, required, allowed=None):
    if not isinstance(value, dict) or not required <= set(value) or not set(value) <= (allowed or required):
        raise ValueError('Fields are outside the protocol metadata whitelist')


def _id(value):
    if not isinstance(value, str) or ID.fullmatch(value) is None:
        raise ValueError('Invalid protocol identifier')


def _aic(value):
    if not isinstance(value, str) or not is_valid_aic_format(value) or value != value.upper():
        raise ValueError('Invalid real agent identity')


def _number(value, *, integer=False, minimum=0, maximum=2**53 - 1):
    if (type(value) not in ({int} if integer else {int, float})
            or (type(value) is float and not math.isfinite(value)) or not minimum <= value <= maximum):
        raise ValueError('Invalid numeric metadata')


def validate_config(config):
    _keys(config, {'broker', 'sources'})
    if _validate_broker(config['broker']) != BROKER:
        raise ValueError('Only the explicitly authorized official broker is allowed')
    if not isinstance(config['sources'], list) or len(config['sources']) != 3:
        raise ValueError('Exactly three registered sources are required')
    seen = set()
    for source in config['sources']:
        _keys(source, {'role', 'aic'})
        role = source['role']
        if not isinstance(role, str) or role in seen or CURRENT_AICS.get(role) != source['aic']:
            raise ValueError('Source role or current registered AIC is not authorized')
        seen.add(role)
    return config


def metadata_sources(config, *, test_log_root=None):
    validate_config(config)
    sources = []
    root = Path(test_log_root).resolve() if test_log_root is not None else Path('/var/log')
    for source in config['sources']:
        role, aic = source['role'], source['aic']
        digest = hashlib.sha256(aic.encode()).hexdigest()
        for log_type, collector in COLLECTORS[role]:
            path = root / f'gongwei-{role}' / 'amp' / f'amp_{log_type}_{collector}_{digest}.jsonl'
            sources.append({'role': role, 'aic': aic, 'log_type': log_type,
                            'log_path': path, 'key': role + ':' + log_type})
    return sources


def validate_record(raw, log_type, aic):
    if log_type not in TOPICS or aic not in CURRENT_AICS.values() or not isinstance(raw, bytes) or len(raw) > MAX_LINE_BYTES:
        raise ValueError('Unapproved metadata source or record size')
    value = _decode(raw)
    required = {'schema_version', 'log_id', 'log_type', 'timestamp', 'aic', 'correlation_id', 'body'}
    _keys(value, required, required | {'trace_id', 'span_id', 'parent_span_id'})
    if value['schema_version'] != '1.0' or value['log_type'] != log_type or value['aic'] != aic:
        raise ValueError('Unexpected metadata identity or schema')
    log_id = value['log_id']
    if not isinstance(log_id, str) or str(uuid.UUID(log_id)) != log_id:
        raise ValueError('Invalid original SDK log ID')
    if not isinstance(value['timestamp'], str) or len(value['timestamp']) > 40:
        raise ValueError('Invalid event timestamp')
    timestamp = datetime.fromisoformat(value['timestamp'])
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError('Event timestamp must have timezone')
    _id(value['correlation_id'])
    for key, size in (('trace_id', 32), ('span_id', 16), ('parent_span_id', 16)):
        if key in value and (not isinstance(value[key], str)
                            or re.fullmatch(f'[0-9a-f]{{{size}}}', value[key]) is None or int(value[key], 16) == 0):
            raise ValueError('Invalid trace identity')
    body = value['body']
    if log_type == 'access':
        _keys(body, {'request', 'response', 'caller', 'callee'},
              {'request', 'response', 'caller', 'callee', 'durationMs', 'error'})
        _keys(body['request'], {'method', 'url', 'route'})
        if body['request']['method'] not in {'start', 'get', 'continue', 'complete', 'cancel'} or body['request']['url'] != '/rpc' or body['request']['route'] != '/rpc':
            raise ValueError('Unapproved RPC method or route')
        _keys(body['response'], {'statusCode'})
        _number(body['response']['statusCode'], integer=True, minimum=100, maximum=599)
        for participant in ('caller', 'callee'):
            item = body[participant]
            _keys(item, {'aic'}, {'aic', 'serviceName'})
            _aic(item['aic'])
            if 'serviceName' in item and item['serviceName'] not in {'gongwei-leader_rpc', 'gongwei-leader_mq', 'gongwei-partner_mq'}:
                raise ValueError('Unapproved service metadata')
        if body['callee']['aic'] != aic:
            raise ValueError('Callee identity must match the actual local collector')
        if 'durationMs' in body:
            _number(body['durationMs'])
        if 'error' in body:
            _keys(body['error'], {'code'})
            code = body['error']['code']
            if type(code) is int:
                _number(code, integer=True, minimum=-(2**31), maximum=2**31 - 1)
            elif code not in {'DISPATCH_EXCEPTION', 'DISPATCH_CANCELED'}:
                raise ValueError('Unapproved error code')
        AccessLogRecord.model_validate(value, strict=True)
    else:
        required_body = {'eventType', 'operationName', 'system', 'destination', 'messageId', 'attributes'}
        _keys(body, required_body, required_body | {'subscriptionName', 'payloadSizeBytes', 'deliveryAttempt', 'settlement'})
        event = body['eventType']
        if not isinstance(event, str) or OPERATIONS.get(event) != body['operationName'] or body['system'] != 'rabbitmq':
            raise ValueError('Unapproved SDK messaging operation')
        _keys(body['destination'], {'name'}, {'name', 'kind', 'virtualHost'})
        _id(body['destination']['name'])
        if 'kind' in body['destination'] and body['destination']['kind'] not in {'exchange', 'queue'}:
            raise ValueError('Unapproved messaging destination kind')
        if 'virtualHost' in body['destination'] and body['destination']['virtualHost'] not in {'acps', '/acps'}:
            raise ValueError('Unapproved messaging virtual host')
        if 'subscriptionName' in body:
            _id(body['subscriptionName'])
        _id(body['messageId'])
        _keys(body['attributes'], {'taskId'}, {'taskId', 'msgType'})
        if body['attributes']['taskId'] != value['correlation_id']:
            raise ValueError('Message must retain its real task correlation')
        if 'msgType' in body['attributes'] and body['attributes']['msgType'] not in {'task-command', 'task-result'}:
            raise ValueError('Unapproved task message type')
        for key, minimum in (('payloadSizeBytes', 0), ('deliveryAttempt', 1)):
            if key in body:
                _number(body[key], integer=True, minimum=minimum)
        if 'settlement' in body:
            if event in {'send', 'receive'}:
                raise ValueError('Settlement metadata requires a real settlement event')
            _keys(body['settlement'], {'latencyMs'})
            _number(body['settlement']['latencyMs'])
        MessageLogRecord.model_validate(value, strict=True)
    return value


def _source_owner_ids():
    if os.name != 'posix':
        raise RuntimeError('Production source ownership requires POSIX service accounts')
    import pwd
    accounts = {role: pwd.getpwnam(name) for role, name in SOURCE_USERS.items()}
    return {role: (account.pw_uid, account.pw_gid) for role, account in accounts.items()}


def _open_file(path, *, owner_uid=None, owner_gid=None, max_bytes=MAX_FILE_BYTES, private=False):
    # Use directory descriptors on POSIX: no parent or leaf symlink can redirect
    # the read, even if a directory changes between checking and opening.
    flags = os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0)
    parent_fd = None
    if os.name == 'posix':
        directory_flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW
        parent_fd = os.open(path.anchor, directory_flags)
        try:
            for part in path.parts[1:-1]:
                next_fd = os.open(part, directory_flags, dir_fd=parent_fd)
                os.close(parent_fd)
                parent_fd = next_fd
            descriptor = os.open(path.name, flags, dir_fd=parent_fd)
        finally:
            os.close(parent_fd)
    else:
        for item in (path, *path.parents):
            if item.is_symlink():
                raise ValueError('Symlink metadata path')
        descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or info.st_size > max_bytes
                or (owner_uid is not None and info.st_uid != owner_uid)
                or (owner_gid is not None and info.st_gid != owner_gid)):
            raise ValueError('Metadata file failed source ownership, size or regular-file checks')
        if private and os.name == 'posix' and stat.S_IMODE(info.st_mode) != 0o600:
            raise ValueError('Metadata state permissions must be 0600')
        return os.fdopen(descriptor, 'rb', buffering=0), info
    except BaseException:
        os.close(descriptor)
        raise


def _anchor(handle, offset):
    handle.seek(max(0, offset - 64))
    return hashlib.sha256(handle.read(min(64, offset))).hexdigest()


class MetadataForwarder:
    def __init__(self, *, config, send, state_dir=STATE_DIR, test_owner_ids=None,
                 test_log_root=None, report=_report, max_records=100):
        self.sources = metadata_sources(config, test_log_root=test_log_root)
        if test_owner_ids is not None and test_log_root is None:
            raise ValueError('Owner overrides require an isolated test log root')
        self.refresh_owners = test_owner_ids is None
        self.owner_ids = _source_owner_ids() if test_owner_ids is None else dict(test_owner_ids)
        if set(self.owner_ids) != set(SOURCE_USERS):
            raise ValueError('All three service account ownership pairs are required')
        for uid, gid in self.owner_ids.values():
            _number(uid, integer=True, maximum=2**32 - 1)
            _number(gid, integer=True, maximum=2**32 - 1)
        self.log_root = Path(test_log_root).resolve() if test_log_root is not None else Path('/var/log')
        self.send, self.report = send, report
        _number(max_records, integer=True, minimum=1, maximum=1000)
        self.max_records, self.failures = max_records, 0
        self.state_dir = Path(state_dir).absolute()
        self.state_path = self.state_dir / 'cursor.json'
        self.lock_fd = None
        self.state_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = self.state_dir.lstat()
        if not stat.S_ISDIR(info.st_mode) or info.st_nlink < 1:
            raise ValueError('State directory must be an ordinary private directory')
        if os.name == 'posix' and (stat.S_IMODE(info.st_mode) != 0o700 or info.st_uid != os.geteuid()):
            raise ValueError('State directory must be owned by this service with mode 0700')
        for parent in self.state_dir.parents:
            if parent.is_symlink():
                raise ValueError('Symlink state directory')
        lock_path = self.state_dir / 'cursor.lock'
        if lock_path.exists() or lock_path.is_symlink():
            with _open_file(lock_path, private=True, max_bytes=1)[0]:
                pass
        self.lock_fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            if os.name == 'posix':
                import fcntl
                fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            else:
                import msvcrt
                if os.fstat(self.lock_fd).st_size == 0:
                    os.write(self.lock_fd, b'0')
                os.lseek(self.lock_fd, 0, os.SEEK_SET)
                msvcrt.locking(self.lock_fd, msvcrt.LK_NBLCK, 1)
            self.state = self._load()
        except BaseException:
            self.close()
            raise

    def close(self):
        if self.lock_fd is not None:
            os.close(self.lock_fd)
            self.lock_fd = None

    def _source_path(self, source):
        # systemd LogsDirectory with DynamicUser may use a symlink/bind mount
        # into /var/log/private. Resolve the parent once, then securely open
        # that exact approved directory; the leaf itself is never followed.
        parent = source['log_path'].parent.resolve(strict=True)
        allowed = {self.log_root / f"gongwei-{source['role']}" / 'amp',
                   self.log_root / 'private' / f"gongwei-{source['role']}" / 'amp'}
        if parent not in allowed:
            raise ValueError('Source directory is outside its fixed systemd log directory')
        return parent / source['log_path'].name

    def _live_source(self, handle, role):
        info = os.fstat(handle.fileno())
        uid, gid = self.owner_ids[role]
        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1
                or (info.st_uid, info.st_gid) != (uid, gid) or info.st_size > MAX_FILE_BYTES):
            raise ValueError('Source changed during metadata validation')
        return info

    def _load(self):
        if not self.state_path.exists() and not self.state_path.is_symlink():
            return {'version': 1, 'cursors': {}, 'ledger': {}}
        owner = os.geteuid() if os.name == 'posix' else None
        handle, _ = _open_file(self.state_path, owner_uid=owner, max_bytes=MAX_STATE_BYTES, private=True)
        with handle:
            value = _decode(handle.read(MAX_STATE_BYTES + 1))
        _keys(value, {'version', 'cursors', 'ledger'})
        if type(value['version']) is not int or value['version'] != 1 or not isinstance(value['cursors'], dict) or not isinstance(value['ledger'], dict) or len(value['ledger']) > MAX_LEDGER:
            raise ValueError('Invalid durable state')
        keys = {source['key'] for source in self.sources}
        for key, cursor in value['cursors'].items():
            if key not in keys:
                raise ValueError('Unknown durable source')
            _keys(cursor, {'device', 'inode', 'offset', 'anchor'})
            for field in ('device', 'inode', 'offset'):
                _number(cursor[field], integer=True, maximum=2**128 - 1)
            if not isinstance(cursor['anchor'], str) or re.fullmatch('[0-9a-f]{64}', cursor['anchor']) is None or cursor['offset'] > MAX_FILE_BYTES:
                raise ValueError('Invalid durable cursor')
        for key, receipt in value['ledger'].items():
            parts = key.split(':')
            if len(parts) != 3 or parts[0] not in TOPICS or parts[1] not in CURRENT_AICS.values() or str(uuid.UUID(parts[2])) != parts[2]:
                raise ValueError('Invalid acknowledged log identity')
            _keys(receipt, {'digest', 'partition', 'offset'})
            if not isinstance(receipt['digest'], str) or re.fullmatch('[0-9a-f]{64}', receipt['digest']) is None:
                raise ValueError('Invalid acknowledged record digest')
            for field in ('partition', 'offset'):
                _number(receipt[field], integer=True, maximum=2**63 - 1)
        return value

    def _persist(self, updated):
        if self.state_path.exists() or self.state_path.is_symlink():
            with _open_file(self.state_path, private=True, max_bytes=MAX_STATE_BYTES)[0]:
                pass
        raw = json.dumps(updated, ensure_ascii=True, separators=(',', ':')).encode()
        if len(raw) > MAX_STATE_BYTES:
            raise ValueError('Durable metadata state is too large')
        temporary = self.state_dir / ('cursor-' + uuid.uuid4().hex + '.tmp')
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0), 0o600)
        try:
            with os.fdopen(descriptor, 'wb') as handle:
                handle.write(raw)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self.state_path)
            if os.name == 'posix':
                directory = os.open(self.state_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                try:
                    os.fsync(directory)
                finally:
                    os.close(directory)
        finally:
            with suppress(FileNotFoundError):
                temporary.unlink()
        self.state = updated

    async def poll_once(self):
        if self.refresh_owners:
            try:
                # DynamicUser allocation can change after a business service
                # restarts. Re-resolve only the fixed service names, never trust
                # file ownership as the source of the expected identity.
                self.owner_ids = _source_owner_ids()
            except Exception:
                self.failures += 1
                return
        remaining = self.max_records
        for source in self.sources:
            if remaining <= 0:
                break
            try:
                uid, gid = self.owner_ids[source['role']]
                handle, info = _open_file(self._source_path(source), owner_uid=uid,
                                         owner_gid=gid, max_bytes=MAX_FILE_BYTES)
                with handle:
                    cursor = self.state['cursors'].get(source['key'])
                    offset = 0
                    if cursor and cursor['device'] == info.st_dev and cursor['inode'] == info.st_ino and cursor['offset'] <= info.st_size and _anchor(handle, cursor['offset']) == cursor['anchor']:
                        offset = cursor['offset']
                    while remaining > 0:
                        handle.seek(offset)
                        line = handle.readline(MAX_LINE_BYTES + 2)
                        if not line or not line.endswith(b'\n'):
                            break
                        raw = line[:-1].removesuffix(b'\r')
                        value = validate_record(raw, source['log_type'], source['aic'])
                        end = handle.tell()
                        record_anchor = _anchor(handle, end)
                        digest = hashlib.sha256(raw).hexdigest()
                        key = f"{source['log_type']}:{source['aic']}:{value['log_id']}"
                        receipt = self.state['ledger'].get(key)
                        if receipt and receipt['digest'] != digest:
                            raise ValueError('Original log ID was reused for different content')
                        if not receipt:
                            self._live_source(handle, source['role'])
                            handle.seek(offset)
                            if handle.read(len(line)) != line:
                                raise ValueError('Source record changed before send')
                            ack = await self.send(source['log_type'], source['aic'], raw)
                            if ack is None:
                                raise ValueError('Kafka broker acknowledgement is required')
                            _number(ack.partition, integer=True, maximum=2**31 - 1)
                            _number(ack.offset, integer=True, maximum=2**63 - 1)
                            receipt = {'digest': digest, 'partition': ack.partition, 'offset': ack.offset}
                        updated = {'version': 1, 'cursors': dict(self.state['cursors']), 'ledger': dict(self.state['ledger'])}
                        already_sent = key in updated['ledger']
                        updated['ledger'][key] = receipt
                        while len(updated['ledger']) > MAX_LEDGER:
                            updated['ledger'].pop(next(iter(updated['ledger'])))
                        try:
                            self._live_source(handle, source['role'])
                            handle.seek(offset)
                            unchanged = handle.read(len(line)) == line and _anchor(handle, end) == record_anchor
                        except ValueError:
                            unchanged = False
                        if unchanged:
                            updated['cursors'][source['key']] = {'device': info.st_dev, 'inode': info.st_ino,
                                'offset': end, 'anchor': record_anchor}
                        else:
                            # The ACK is real, but it says nothing about a file
                            # truncated/replaced while awaiting the broker.
                            updated['cursors'].pop(source['key'], None)
                        self._persist(updated)
                        if not already_sent:
                            self.report({'log_type': source['log_type'], 'log_id': value['log_id'], 'aic': source['aic'],
                                         'partition': receipt['partition'], 'offset': receipt['offset']})
                        offset = end
                        remaining -= 1
                        if not unchanged:
                            break
            except FileNotFoundError:
                continue  # Collectors create files only when real events occur.
            except asyncio.CancelledError:
                raise
            except Exception:
                self.failures += 1  # Never echo rejected contents or exception text.


class KafkaMetadataSender:
    def __init__(self, broker, *, producer_factory=None, clock=time.monotonic):
        if _validate_broker(broker) != BROKER:
            raise ValueError('Only the official explicitly authorized broker is allowed')
        self.broker, self.factory, self.clock = broker, producer_factory, clock
        self.producer, self.next_attempt, self.backoff = None, 0.0, 1.0

    async def close(self):
        producer, self.producer = self.producer, None
        if producer is not None:
            with suppress(Exception):
                await asyncio.wait_for(producer.stop(), 5)

    async def send(self, log_type, aic, raw):
        validate_record(raw, log_type, aic)
        if self.clock() < self.next_attempt:
            raise RetryBackoff()
        try:
            if self.producer is None:
                factory = self.factory
                if factory is None:
                    import aiokafka
                    if aiokafka.__version__ != '0.12.0':
                        raise RuntimeError('Protocol metadata forwarding requires aiokafka 0.12.0')
                    factory = aiokafka.AIOKafkaProducer
                self.producer = factory(bootstrap_servers=self.broker,
                    client_id='gongwei-amp-metadata-forwarder', security_protocol='PLAINTEXT',
                    request_timeout_ms=8000, acks='all')
                _all_topics_metadata_only(self.producer.client)
                await asyncio.wait_for(self.producer.start(), 10)
                metadata = await asyncio.wait_for(self.producer.client.fetch_all_metadata(), 10)
                if not set(TOPICS.values()) <= metadata.topics():
                    raise TopicUnavailable()
            if TOPICS[log_type] not in self.producer.client.cluster.topics():
                raise TopicUnavailable()
            receipt = await asyncio.wait_for(self.producer.send_and_wait(
                TOPICS[log_type], value=raw, key=aic.encode()), 10)
            if receipt is None or receipt.topic != TOPICS[log_type]:
                raise ValueError('ACK must identify the actual official destination topic')
            _number(receipt.partition, integer=True, maximum=2**31 - 1)
            _number(receipt.offset, integer=True, maximum=2**63 - 1)
            self.backoff, self.next_attempt = 1.0, 0.0
            return receipt
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.close()
            self.next_attempt = self.clock() + self.backoff
            self.backoff = min(15.0, self.backoff * 2)
            raise


async def run_forwarder(forwarder, sender, stop, *, max_seconds=None):
    async def polling():
        while True:
            await forwarder.poll_once()
            await asyncio.sleep(1)
    worker, stopping = asyncio.create_task(polling()), asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait({worker, stopping}, timeout=max_seconds, return_when=asyncio.FIRST_COMPLETED)
        if worker in done:
            await worker
    finally:
        worker.cancel(); stopping.cancel()
        await asyncio.gather(worker, stopping, return_exceptions=True)
        await sender.close()
        forwarder.close()


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', required=True)
    parser.add_argument('--public-protocol-metadata-plaintext', action='store_true', required=True,
                        help='Explicitly authorize only registered protocol metadata on the official PLAINTEXT broker')
    parser.add_argument('--max-seconds', type=_positive_seconds)
    return parser


async def _main(args):
    handle, _ = _open_file(Path(args.config).absolute(), max_bytes=64 * 1024)
    with handle:
        config = validate_config(_decode(handle.read(64 * 1024 + 1)))
    # Library diagnostics can include remote broker messages. Output only ACKs.
    kafka_logger = logging.getLogger('aiokafka')
    kafka_logger.addHandler(logging.NullHandler())
    kafka_logger.propagate = False
    kafka_logger.disabled = True
    sender = KafkaMetadataSender(config['broker'])
    forwarder = MetadataForwarder(config=config, send=sender.send)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed = []
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous = signal.getsignal(sig)
            loop.add_signal_handler(sig, stop.set)
            installed.append((sig, previous))
        await run_forwarder(forwarder, sender, stop, max_seconds=args.max_seconds)
    finally:
        for sig, previous in installed:
            loop.remove_signal_handler(sig)
            signal.signal(sig, previous)
        forwarder.close()
        await sender.close()


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        asyncio.run(_main(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        _report({'error_type': type(exc).__name__})
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
