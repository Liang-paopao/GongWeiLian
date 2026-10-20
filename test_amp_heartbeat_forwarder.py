"""Offline tests: no Kafka, credentials, live service, or production log access."""
import asyncio
import importlib.util
import io
import json
import math
import sys
import tempfile
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from contextlib import redirect_stderr
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch


def implementation(case):
    case.assertIsNotNone(importlib.util.find_spec("amp_heartbeat_forwarder"),
                         "The isolated heartbeat forwarder has not been implemented")
    import amp_heartbeat_forwarder
    return amp_heartbeat_forwarder


class ForwarderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.module = implementation(self)
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.path = self.root / "gongwei-leader" / "amp" / "amp_heartbeat_leader_abc.jsonl"
        self.path.parent.mkdir(parents=True)
        self.now = datetime(2026, 10, 7, 2, 0, tzinfo=timezone.utc)
        self.ack = SimpleNamespace(partition=0, offset=12, timestamp_type=1)
        self.send = AsyncMock(return_value=self.ack)
        self.active = AsyncMock(return_value=True)
        self.events = []
        self.source = {"role": "leader", "aic": "aic-leader", "log_path": str(self.path)}
        self.forwarder = self.module.HeartbeatForwarder(
            sources=[self.source], send=self.send, is_active=self.active,
            clock=lambda: self.now, report=self.events.append, test_log_root=self.root)

    def record(self, **changes):
        value = {"schema_version": "1.0", "log_id": str(uuid.uuid4()),
                 "log_type": "heartbeat", "timestamp": self.now.isoformat(),
                 "aic": "aic-leader", "body": {"uptimeSeconds": 10.5}}
        value.update(changes)
        return value

    def write(self, record, suffix=b"\n"):
        raw = json.dumps(record, ensure_ascii=False).encode()
        self.path.write_bytes(raw + suffix)
        return raw

    async def test_forwards_exact_original_bytes_only_after_ack_and_deduplicates(self):
        record = self.record()
        raw = self.write(record)
        await self.forwarder.poll_once()
        await self.forwarder.poll_once()
        self.send.assert_awaited_once_with("aic-leader", raw)
        self.assertEqual(self.events, [{"role": "leader", "log_id": record["log_id"],
                                       "partition": 0, "offset": 12, "timestamp_type": 1}])

    async def test_no_receipt_is_not_an_ack(self):
        self.write(self.record())
        self.send.return_value = None
        await self.forwarder.poll_once()
        self.send.return_value = self.ack
        await self.forwarder.poll_once()
        self.assertEqual(self.send.await_count, 2)
        self.assertEqual(sum("offset" in item for item in self.events), 1)

    async def test_inactive_service_never_sends(self):
        self.write(self.record())
        self.active.return_value = False
        await self.forwarder.poll_once()
        self.send.assert_not_awaited()

    async def test_failure_retries_only_while_latest_record_is_fresh(self):
        self.write(self.record())
        self.send.side_effect = [ConnectionError("do-not-log-payload"), self.ack]
        await self.forwarder.poll_once()
        await self.forwarder.poll_once()
        self.assertEqual(self.send.await_count, 2)
        self.assertNotIn("do-not-log-payload", json.dumps(self.events))
        self.assertEqual(sum("offset" in item for item in self.events), 1)
        self.send.reset_mock()
        self.send.side_effect = ConnectionError("offline")
        self.write(self.record())
        await self.forwarder.poll_once()
        self.now += timedelta(seconds=26)
        await self.forwarder.poll_once()
        self.assertEqual(self.send.await_count, 1)

    async def test_rejects_historical_stale_future_and_naive_timestamps(self):
        start = self.now
        self.now += timedelta(seconds=40)
        for timestamp in [(start-timedelta(seconds=1)).isoformat(),
                          (self.now-timedelta(seconds=26)).isoformat(),
                          (self.now+timedelta(seconds=3)).isoformat(),
                          self.now.replace(tzinfo=None).isoformat()]:
            with self.subTest(timestamp=timestamp):
                self.write(self.record(timestamp=timestamp))
                await self.forwarder.poll_once()
        self.send.assert_not_awaited()

    async def test_refreshes_clock_after_waiting_for_service_check(self):
        self.write(self.record())
        async def slow_check(role):
            self.now += timedelta(seconds=26)
            return True
        self.active.side_effect = slow_check
        await self.forwarder.poll_once()
        self.send.assert_not_awaited()

    async def test_schema_rejects_extra_fields_wrong_identity_and_invalid_uptime(self):
        bad = [self.record(observedTimestamp=self.now.isoformat()), self.record(aic="other"),
               self.record(log_type="task"), self.record(schema_version="2.0"),
               self.record(body={"uptimeSeconds": 1, "password": "never-send"})]
        bad += [self.record(body={"uptimeSeconds": value}) for value in
                [-1, math.nan, math.inf, True, "1", None]]
        for record in bad:
            with self.subTest(record=list(record)):
                self.write(record)
                await self.forwarder.poll_once()
        self.send.assert_not_awaited()
        self.assertNotIn("never-send", json.dumps(self.events))

    async def test_missing_bad_or_incomplete_latest_line_is_not_replaced_by_older_data(self):
        await self.forwarder.poll_once()
        raw = self.write(self.record(), suffix=b"")
        await self.forwarder.poll_once()
        self.path.write_bytes(raw + b"\nnot-json-secret\n")
        await self.forwarder.poll_once()
        self.path.write_bytes(raw + b"\n{\"incomplete\"")
        await self.forwarder.poll_once()
        self.send.assert_awaited_once_with("aic-leader", raw)
        self.assertNotIn("not-json-secret", json.dumps(self.events))

    async def test_tail_limit_skips_oversized_line_but_handles_large_history(self):
        raw = json.dumps(self.record()).encode()
        self.path.write_bytes(b"old\n" * 30000 + raw + b"\n")
        await self.forwarder.poll_once()
        self.send.assert_awaited_once_with("aic-leader", raw)
        self.send.reset_mock()
        self.path.write_bytes(b"x" * (64 * 1024 + 1) + b"\n")
        await self.forwarder.poll_once()
        self.send.assert_not_awaited()

    async def test_duplicate_json_keys_are_rejected(self):
        raw = json.dumps(self.record()).encode()
        self.path.write_bytes(raw[:-1] + b',"body":{"uptimeSeconds":1}}\n')
        await self.forwarder.poll_once()
        self.send.assert_not_awaited()

    async def test_restart_does_not_replay_a_record_from_before_process_start(self):
        self.write(self.record())
        self.now += timedelta(seconds=1)
        restarted = self.module.HeartbeatForwarder(
            sources=[self.source], send=self.send, is_active=self.active,
            clock=lambda: self.now, report=self.events.append, test_log_root=self.root)
        await restarted.poll_once()
        self.send.assert_not_awaited()

    async def test_symlink_to_other_file_is_not_opened(self):
        target = self.root / "other.jsonl"
        target.write_bytes(json.dumps(self.record()).encode() + b"\n")
        try:
            self.path.symlink_to(target)
        except OSError:
            self.skipTest("Symlink creation unavailable; Linux acceptance covers this gate")
        await self.forwarder.poll_once()
        self.send.assert_not_awaited()


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.module = implementation(self)

    def config(self):
        return {"broker": "wt.ioa.pub:19092", "sources": [
            {"role": role, "aic": "aic-" + role,
             "log_path": f"/var/log/gongwei-{role}/amp/amp_heartbeat_test.jsonl"}
            for role in ("leader", "resource-inbox", "workorder-inbox")]}

    def test_configuration_allows_only_explicit_broker_and_exact_three_sources(self):
        parsed = self.module.validate_config(self.config())
        self.assertEqual(parsed["broker"], "wt.ioa.pub:19092")
        for config in [{"sources": self.config()["sources"]},
                       {**self.config(), "username": "credential"},
                       {**self.config(), "broker": "user:secret@wt.ioa.pub:19092"},
                       {**self.config(), "sources": self.config()["sources"][:1]}]:
            with self.subTest(keys=list(config)), self.assertRaises(ValueError):
                self.module.validate_config(config)

    def test_source_path_role_glob_and_escape_restrictions(self):
        for path in ["/etc/passwd", "/var/log/gongwei-leader/amp/task.jsonl",
                     "/var/log/gongwei-resource-inbox/amp/amp_heartbeat_test.jsonl",
                     "/var/log/gongwei-leader/amp/../amp_heartbeat_test.jsonl",
                     "/var/log/gongwei-leader/amp/amp_heartbeat_*.jsonl"]:
            config = self.config()
            config["sources"][0]["log_path"] = path
            with self.subTest(path=path), self.assertRaises(ValueError):
                self.module.validate_config(config)

    def test_cli_requires_explicit_plaintext_consent_and_has_no_path_override(self):
        parser = self.module.build_parser()
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["--config", "config.json"])
        args = parser.parse_args(["--config", "config.json", "--public-heartbeat-plaintext",
                                  "--max-seconds", "3"])
        self.assertEqual(args.max_seconds, 3)
        with redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            parser.parse_args(["--config", "config.json", "--public-heartbeat-plaintext",
                               "--test-log-root", "/tmp"])


class KafkaSenderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.module = implementation(self)
        self.now = 100.0
        self.producers = []
        self.options = []
        self.metadata_calls = []
        self.topic_exists = True
        def factory(**options):
            self.options.append(options)
            metadata = SimpleNamespace(topics=lambda: {"amp.heartbeat"} if self.topic_exists else set())
            async def metadata_update(cluster_metadata, topics):
                self.metadata_calls.append((cluster_metadata, list(topics)))
                return True
            client = SimpleNamespace(cluster=metadata, _metadata_update=metadata_update)
            async def start():
                # A producer may start its metadata synchronization immediately.
                await client._metadata_update(metadata, {"amp.heartbeat"})
            async def fetch_all_metadata():
                await client._metadata_update(metadata, [])
                return metadata
            client.fetch_all_metadata = AsyncMock(side_effect=fetch_all_metadata)
            producer = SimpleNamespace(start=AsyncMock(side_effect=start), stop=AsyncMock(), client=client,
                send_and_wait=AsyncMock(return_value=SimpleNamespace(partition=0, offset=9, timestamp_type=1)))
            self.producers.append(producer)
            return producer
        self.sender = self.module.KafkaHeartbeatSender("wt.ioa.pub:19092", producer_factory=factory,
                                                      clock=lambda: self.now)
        self.timestamp = datetime.now(timezone.utc)
        self.payload = json.dumps({"schema_version": "1.0", "log_id": str(uuid.uuid4()),
            "log_type": "heartbeat", "timestamp": self.timestamp.isoformat(), "aic": "aic",
            "body": {"uptimeSeconds": 10}}).encode()
        self.addAsyncCleanup(self.sender.close)

    async def test_metadata_topic_gate_precedes_acknowledged_publish(self):
        ack = await self.sender.send("aic", self.payload)
        self.assertEqual(ack.offset, 9)
        self.producers[0].client.fetch_all_metadata.assert_awaited_once()
        self.producers[0].send_and_wait.assert_awaited_once_with(
            "amp.heartbeat", value=self.payload, key=b"aic")
        self.assertEqual(self.options[0]["security_protocol"], "PLAINTEXT")
        self.assertEqual(self.options[0]["acks"], "all")
        self.assertNotIn("sasl_plain_password", self.options[0])

    async def test_missing_topic_does_not_publish_and_closes_producer(self):
        self.topic_exists = False
        with self.assertRaises(self.module.TopicUnavailable):
            await self.sender.send("aic", self.payload)
        self.producers[0].send_and_wait.assert_not_awaited()
        self.producers[0].stop.assert_awaited_once()

    async def test_network_failure_rebuilds_producer_after_bounded_backoff(self):
        await self.sender.send("aic", self.payload)
        self.producers[0].send_and_wait.side_effect = ConnectionError("offline")
        with self.assertRaises(ConnectionError):
            await self.sender.send("aic", self.payload)
        self.producers[0].stop.assert_awaited_once()
        with self.assertRaises(self.module.RetryBackoff):
            await self.sender.send("aic", self.payload)
        self.assertEqual(len(self.producers), 1)
        self.now += 15
        await self.sender.send("aic", self.payload)
        self.assertEqual(len(self.producers), 2)

    async def test_repeated_failures_never_back_off_longer_than_fifteen_seconds(self):
        self.topic_exists = False
        for _ in range(7):
            with self.assertRaises(self.module.TopicUnavailable):
                await self.sender.send("aic", self.payload)
            self.now += 15
        self.assertEqual(len(self.producers), 7)

    async def test_heartbeat_expired_during_connection_never_reaches_publish(self):
        with patch.object(self.module, "_utc_now", return_value=self.timestamp + timedelta(seconds=26)):
            with self.assertRaises(ValueError):
                await self.sender.send("aic", self.payload)
        self.producers[0].client.fetch_all_metadata.assert_awaited_once()
        self.producers[0].send_and_wait.assert_not_awaited()

    async def test_sender_never_transmits_unvalidated_raw_input(self):
        with self.assertRaises(ValueError):
            await self.sender.send("aic", b'{"password":"must-not-leave"}')
        self.producers[0].send_and_wait.assert_not_awaited()

    async def test_service_stopping_during_connection_prevents_publish(self):
        self.sender.is_active = AsyncMock(return_value=False)
        with self.assertRaises(ValueError):
            await self.sender.send("aic", self.payload)
        self.sender.is_active.assert_awaited_once_with("aic")
        self.producers[0].send_and_wait.assert_not_awaited()

    async def test_all_metadata_updates_including_background_use_no_named_topics(self):
        await self.sender.send("aic", self.payload)
        client = self.producers[0].client
        other_cluster = SimpleNamespace()
        updated = await client._metadata_update(other_cluster, {"amp.heartbeat", "other-topic"})
        await client.fetch_all_metadata()
        self.assertTrue(updated)
        self.assertTrue(all(topics == [] for _, topics in self.metadata_calls))
        self.assertIs(self.metadata_calls[2][0], other_cluster)
        self.assertIs(self.metadata_calls[0][0], client.cluster)

    async def test_deleted_topic_after_background_refresh_never_publishes_again(self):
        await self.sender.send("aic", self.payload)
        producer = self.producers[0]
        self.topic_exists = False
        await producer.client._metadata_update(producer.client.cluster, {"amp.heartbeat"})
        with self.assertRaises(self.module.TopicUnavailable):
            await self.sender.send("aic", self.payload)
        self.assertEqual(producer.send_and_wait.await_count, 1)
        self.assertTrue(all(topics == [] for _, topics in self.metadata_calls))

    async def test_missing_or_changed_private_metadata_interface_fails_before_start(self):
        original_factory = self.sender.factory
        for replacement in (None, lambda cluster_metadata, topics: True,
                            AsyncMock()):
            def incompatible(**options):
                producer = original_factory(**options)
                producer.client._metadata_update = replacement
                return producer
            sender = self.module.KafkaHeartbeatSender("wt.ioa.pub:19092", producer_factory=incompatible)
            try:
                with self.subTest(replacement=type(replacement).__name__):
                    caught = None
                    try:
                        await sender.send("aic", self.payload)
                    except Exception as exc:
                        caught = exc
                    self.assertIsInstance(caught, RuntimeError)
                    self.producers[-1].start.assert_not_awaited()
                    self.producers[-1].send_and_wait.assert_not_awaited()
            finally:
                await sender.close()

    async def test_unpinned_aiokafka_version_is_rejected_before_constructing_producer(self):
        factory = self.sender.factory
        sender = self.module.KafkaHeartbeatSender("wt.ioa.pub:19092")
        fresh = json.loads(self.payload)
        fresh["timestamp"] = datetime.now(timezone.utc).isoformat()
        try:
            with patch.dict(sys.modules, {"aiokafka": SimpleNamespace(__version__="0.13.0",
                                                                     AIOKafkaProducer=factory)}):
                with self.assertRaises(RuntimeError):
                    await sender.send("aic", json.dumps(fresh).encode())
            self.assertEqual(self.producers, [])
        finally:
            await sender.close()


class RunLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_stop_cancels_inflight_poll_and_closes_sender(self):
        module = implementation(self)
        stop = asyncio.Event()
        entered = asyncio.Event()
        async def poll():
            entered.set()
            await asyncio.Event().wait()
        forwarder = SimpleNamespace(poll_once=poll)
        sender = SimpleNamespace(close=AsyncMock())
        running = asyncio.create_task(module.run_forwarder(forwarder, sender, stop))
        await asyncio.wait_for(entered.wait(), 1)
        stop.set()
        await asyncio.wait_for(running, 1)
        sender.close.assert_awaited_once()

    async def test_max_seconds_is_bounded_and_closes_sender(self):
        module = implementation(self)
        sender = SimpleNamespace(close=AsyncMock())
        await asyncio.wait_for(module.run_forwarder(SimpleNamespace(poll_once=AsyncMock()),
                                                    sender, asyncio.Event(), max_seconds=0.01), 1)
        sender.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
