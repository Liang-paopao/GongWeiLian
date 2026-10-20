"""Forward fresh, unchanged SDK heartbeat lines to the published AMP topic.

This process transports public heartbeat metadata only. A Kafka ACK does not
establish Discovery liveness or platform verification. No SDK emitter, task
payload, credential loader, environment file, or business transport is used.

Config (all three roles are required)::

    {"broker": "wt.ioa.pub:19092", "sources": [
      {"role": "leader", "aic": "<registered AIC>",
       "log_path": "/var/log/gongwei-leader/amp/amp_heartbeat_<exact-name>.jsonl"},
      ... resource-inbox and workorder-inbox ...]}

Run with --config <file> --public-heartbeat-plaintext. The optional
--max-seconds bounds a diagnostic run; normal service polling is every second.
Install only deploy/requirements-amp.txt in the separate diagnostics venv.
"""
from __future__ import annotations

import argparse
import asyncio
import inspect
import json
import logging
import math
import os
import re
import signal
import stat
import time
import uuid
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit


TOPIC = "amp.heartbeat"
ROLES = frozenset({"leader", "resource-inbox", "workorder-inbox"})
TAIL_LIMIT = 64 * 1024
RECORD_KEYS = {"schema_version", "log_id", "log_type", "timestamp", "aic", "body"}


class TopicUnavailable(RuntimeError):
    pass


class RetryBackoff(RuntimeError):
    pass


def _utc_now():
    return datetime.now(timezone.utc)


def _report(event):
    print(json.dumps(event, ensure_ascii=True, separators=(",", ":")), flush=True)


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value):
    raise ValueError("Nonfinite JSON constant")


def _decode(raw):
    return json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                      parse_constant=_reject_constant)


def _source(source, test_log_root=None):
    if not isinstance(source, dict) or set(source) != {"role", "aic", "log_path"}:
        raise ValueError("Invalid source fields")
    role, aic, raw_path = source["role"], source["aic"], source["log_path"]
    if not isinstance(role, str) or role not in ROLES:
        raise ValueError("Invalid source role")
    if not isinstance(aic, str) or not aic or len(aic) > 256 or any(c.isspace() for c in aic):
        raise ValueError("Invalid expected AIC")
    if not isinstance(raw_path, str):
        raise ValueError("Invalid heartbeat path")
    if test_log_root is None:
        path = PurePosixPath(raw_path)
        parent = PurePosixPath(f"/var/log/gongwei-{role}/amp")
        valid = path.is_absolute() and path.parent == parent and "\\" not in raw_path
    else:
        path = Path(raw_path)
        parent = Path(test_log_root).resolve() / f"gongwei-{role}" / "amp"
        valid = path.is_absolute() and path.parent == parent
    if (not valid or ".." in path.parts or
            re.fullmatch(r"amp_heartbeat_[A-Za-z0-9_-]+\.jsonl", path.name) is None):
        raise ValueError("Heartbeat path is outside its role directory")
    return {"role": role, "aic": aic, "log_path": Path(raw_path)}


def _validate_broker(broker):
    if not isinstance(broker, str) or any(c.isspace() for c in broker):
        raise ValueError("An explicit broker host and port are required")
    parsed = urlsplit("kafka://" + broker)
    if (not parsed.hostname or not parsed.port or not 1 <= parsed.port <= 65535 or
            parsed.username is not None or parsed.password is not None or parsed.path or
            parsed.query or parsed.fragment or "," in broker):
        raise ValueError("Broker must be host:port without credentials or URL parameters")
    return broker


def validate_config(config):
    if not isinstance(config, dict) or set(config) != {"broker", "sources"}:
        raise ValueError("Config requires only broker and sources")
    _validate_broker(config["broker"])
    sources = config["sources"]
    if not isinstance(sources, list) or len(sources) != 3:
        raise ValueError("Exactly three heartbeat sources are required")
    checked = [_source(source) for source in sources]
    if {s["role"] for s in checked} != ROLES or len({s["aic"] for s in checked}) != 3:
        raise ValueError("Source roles and AICs must be distinct")
    return config


def _last_complete_line(path):
    # DynamicUser's parent log directory may be a systemd-managed symlink.
    # The configured leaf must be an ordinary file, never a symlink or FIFO.
    if path.is_symlink():
        raise ValueError("Symlink heartbeat file")
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
    descriptor = os.open(path, flags)
    try:
        info = os.fstat(descriptor)
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise ValueError("Heartbeat source must be a regular unlinked file")
        offset = max(0, info.st_size - TAIL_LIMIT)
        os.lseek(descriptor, offset, os.SEEK_SET)
        tail = os.read(descriptor, TAIL_LIMIT)
    finally:
        os.close(descriptor)
    end = tail.rfind(b"\n")
    if end < 0:
        return None
    begin = tail.rfind(b"\n", 0, end) + 1
    if begin == 0 and offset > 0:
        return None  # The bounded read began inside this line.
    return tail[begin:end].removesuffix(b"\r") or None


def _record(raw, aic, started_at, now):
    value = _decode(raw)
    if not isinstance(value, dict) or set(value) != RECORD_KEYS:
        raise ValueError("Unexpected heartbeat fields")
    if value["schema_version"] != "1.0" or value["log_type"] != "heartbeat" or value["aic"] != aic:
        raise ValueError("Unexpected heartbeat identity or schema")
    log_id = value["log_id"]
    if not isinstance(log_id, str) or str(uuid.UUID(log_id)) != log_id:
        raise ValueError("Invalid SDK heartbeat log ID")
    body = value["body"]
    if not isinstance(body, dict) or set(body) != {"uptimeSeconds"}:
        raise ValueError("Unexpected heartbeat body")
    uptime = body["uptimeSeconds"]
    if type(uptime) not in {int, float} or not math.isfinite(uptime) or uptime < 0:
        raise ValueError("Invalid heartbeat uptime")
    timestamp = datetime.fromisoformat(value["timestamp"])
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("Heartbeat timestamp requires a timezone")
    if timestamp < started_at or not -2 <= (now - timestamp).total_seconds() <= 25:
        return None
    return value


class HeartbeatForwarder:
    def __init__(self, *, sources, send, is_active, clock=_utc_now, report=_report,
                 test_log_root=None):
        self.sources = [_source(source, test_log_root) for source in sources]
        if not self.sources or len({s["role"] for s in self.sources}) != len(self.sources):
            raise ValueError("Sources must have distinct supported roles")
        self.send, self.is_active, self.clock, self.report = send, is_active, clock, report
        self.started_at = clock()
        if self.started_at.tzinfo is None or self.started_at.utcoffset() is None:
            raise ValueError("Forwarder clock must be timezone-aware")
        self.last_id = {}

    async def poll_once(self):
        for source in self.sources:
            role = source["role"]
            try:
                active = self.is_active(role)
                if inspect.isawaitable(active):
                    active = await active
                if not active:
                    continue
                raw = _last_complete_line(source["log_path"])
                if raw is None:
                    continue
                record = _record(raw, source["aic"], self.started_at, self.clock())
                if record is None or self.last_id.get(role) == record["log_id"]:
                    continue
                receipt = await self.send(source["aic"], raw)
                if (receipt is None or type(receipt.partition) is not int or receipt.partition < 0 or
                        type(receipt.offset) is not int or receipt.offset < 0):
                    raise ValueError("Missing broker acknowledgement")
                self.last_id[role] = record["log_id"]
                self.report({"role": role, "log_id": record["log_id"],
                             "partition": receipt.partition, "offset": receipt.offset,
                             "timestamp_type": getattr(receipt, "timestamp_type", None)})
            except RetryBackoff:
                continue
            except Exception as exc:
                self.report({"role": role, "error_type": type(exc).__name__})


def _all_topics_metadata_only(client):
    """Constrain this pinned 0.12.0 client, including its background refresh.

    Official AIOKafkaClient._metadata_update(cluster_metadata, topics) turns an
    empty topics list into None for MetadataRequest v1 (all topics). Named
    metadata requests can auto-create a deleted topic. Install before start;
    bootstrap/version probes already request no named topics in this version.
    Keep the original cluster object and SDK protocol/response processing.
    """
    original = getattr(client, "_metadata_update", None)
    if not inspect.iscoroutinefunction(original):
        raise RuntimeError("Unsupported aiokafka metadata interface")
    parameters = inspect.signature(original).parameters
    if (tuple(parameters) != ("cluster_metadata", "topics") or
            any(p.kind != inspect.Parameter.POSITIONAL_OR_KEYWORD or
                p.default is not inspect.Parameter.empty for p in parameters.values())):
        raise RuntimeError("Unsupported aiokafka metadata signature")

    async def all_topics(cluster_metadata, topics):
        return await original(cluster_metadata, [])

    client._metadata_update = all_topics


class KafkaHeartbeatSender:
    def __init__(self, broker, *, producer_factory=None, clock=time.monotonic, is_active=None):
        self.broker = _validate_broker(broker)
        self.factory, self.clock = producer_factory, clock
        self.started_at, self.is_active = _utc_now(), is_active
        self.producer = None
        self.next_attempt, self.backoff = 0.0, 1.0

    async def close(self):
        producer, self.producer = self.producer, None
        if producer is not None:
            with suppress(Exception):
                await asyncio.wait_for(producer.stop(), 5)

    async def send(self, aic, payload):
        if self.clock() < self.next_attempt:
            raise RetryBackoff()
        try:
            if self.producer is None:
                factory = self.factory
                if factory is None:
                    import aiokafka
                    if getattr(aiokafka, "__version__", None) != "0.12.0":
                        raise RuntimeError("Heartbeat transport requires aiokafka 0.12.0")
                    factory = aiokafka.AIOKafkaProducer
                self.producer = factory(bootstrap_servers=self.broker,
                    client_id="gongwei-amp-heartbeat-forwarder", security_protocol="PLAINTEXT",
                    request_timeout_ms=8000, acks="all")
                _all_topics_metadata_only(self.producer.client)
                await asyncio.wait_for(self.producer.start(), 10)
                # An all-topics metadata request cannot create a missing topic.
                metadata = await asyncio.wait_for(self.producer.client.fetch_all_metadata(), 10)
                if TOPIC not in metadata.topics():
                    raise TopicUnavailable()
            if TOPIC not in self.producer.client.cluster.topics():
                raise TopicUnavailable()
            # Connection/metadata waits may outlive the heartbeat or source.
            # Validate again immediately before submitting the unchanged bytes.
            if self.is_active is not None and not await self.is_active(aic):
                raise ValueError("Heartbeat source is inactive")
            if _record(payload, aic, self.started_at, _utc_now()) is None:
                raise ValueError("Heartbeat expired before Kafka submission")
            receipt = await asyncio.wait_for(self.producer.send_and_wait(
                TOPIC, value=payload, key=aic.encode("utf-8")), 10)
            self.backoff, self.next_attempt = 1.0, 0.0
            return receipt
        except asyncio.CancelledError:
            raise
        except Exception:
            await self.close()
            self.next_attempt = self.clock() + self.backoff
            self.backoff = min(15.0, self.backoff * 2)
            raise


async def service_is_active(role):
    if role not in ROLES:
        return False
    process = await asyncio.create_subprocess_exec(
        "systemctl", "is-active", "--quiet", f"gongwei-{role}.service",
        stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL)
    try:
        return await asyncio.wait_for(process.wait(), 3) == 0
    finally:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
            await process.wait()


async def run_forwarder(forwarder, sender, stop, *, max_seconds=None):
    async def polling():
        while True:
            await forwarder.poll_once()
            await asyncio.sleep(1)
    worker = asyncio.create_task(polling())
    stopping = asyncio.create_task(stop.wait())
    try:
        done, _ = await asyncio.wait({worker, stopping}, timeout=max_seconds,
                                     return_when=asyncio.FIRST_COMPLETED)
        if worker in done:
            await worker
    finally:
        worker.cancel()
        stopping.cancel()
        await asyncio.gather(worker, stopping, return_exceptions=True)
        await sender.close()


def _positive_seconds(value):
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise argparse.ArgumentTypeError("Seconds must be finite and positive")
    return number


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True)
    parser.add_argument("--public-heartbeat-plaintext", action="store_true", required=True,
                        help="Explicitly allow the published PLAINTEXT heartbeat endpoint")
    parser.add_argument("--max-seconds", type=_positive_seconds)
    return parser


async def _main(args):
    with Path(args.config).open("rb") as handle:
        raw = handle.read(TAIL_LIMIT + 1)
    if len(raw) > TAIL_LIMIT:
        raise ValueError("Config is too large")
    config = validate_config(_decode(raw))
    # Library diagnostics may contain broker messages; emit only our whitelist.
    logging.getLogger("aiokafka").disabled = True
    logging.getLogger("aiokafka").addHandler(logging.NullHandler())
    logging.getLogger("aiokafka").propagate = False
    roles_by_aic = {source["aic"]: source["role"] for source in config["sources"]}
    async def source_active(aic):
        return aic in roles_by_aic and await service_is_active(roles_by_aic[aic])
    sender = KafkaHeartbeatSender(config["broker"], is_active=source_active)
    forwarder = HeartbeatForwarder(sources=config["sources"], send=sender.send,
                                   is_active=service_is_active)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    installed = []
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous = signal.getsignal(sig)
            try:
                loop.add_signal_handler(sig, stop.set)
                native = True
            except NotImplementedError:
                signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
                native = False
            installed.append((sig, previous, native))
        await run_forwarder(forwarder, sender, stop, max_seconds=args.max_seconds)
    finally:
        for sig, previous, native in installed:
            if native:
                loop.remove_signal_handler(sig)
            signal.signal(sig, previous)


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        asyncio.run(_main(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:
        _report({"error_type": type(exc).__name__})
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
