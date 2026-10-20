"""Offline official SDK metadata capture; no AMP network transmission."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from acps_sdk.aip import TaskCommand, TaskCommandType, TextDataItem
from acps_sdk.aip.aip_rpc_model import RpcRequest, RpcRequestParams, RpcResponse, JSONRPCError
from acps_sdk.amp import AccessLogRecord, MessageLogRecord, ErrorInfo, MessageSettlement
from acps_sdk.amp._message_tap import build_receive_body, build_send_body, build_settlement_body

AIC = "1.2.156.3088.1.BUPT.JSQB3Y.GD6IGY.AWF688.0WV9"
PEER = "1.2.156.3088.1.BUPT.JSQB3Y.E164E8.FWIZ4R.03IA"
SECRET = "never-copy-business-secret-token"
TRACE_ID = "1" * 32
RECEIVE_SPAN = "2" * 16
SETTLEMENT_SPAN = "3" * 16


def command(task="task-1", message="message-1"):
    return TaskCommand(id=message, sentAt="2026-10-09T00:00:00Z", senderRole="leader",
                       senderId=PEER, taskId=task, sessionId="session-1", groupId="group-1",
                       command=TaskCommandType.Start, dataItems=[TextDataItem(text=SECRET)])


class AmpTelemetryTests(unittest.IsolatedAsyncioTestCase):
    def telemetry(self):
        from amp_telemetry import AmpTelemetry
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        return AmpTelemetry(role="leader_rpc", aic=AIC, log_dir=Path(temp.name))

    @staticmethod
    def records(path):
        return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]

    def test_module_exists_for_local_metadata_capture(self):
        self.assertIsNotNone(importlib.util.find_spec("amp_telemetry"), "metadata capture is missing")

    async def test_message_send_uses_real_task_id_and_omits_unsafe_fields(self):
        telemetry = self.telemetry()
        body = build_send_body(system="rabbitmq", exchange="group-1.exchange", virtual_host="acps",
                               routing_key="", message_id="message-1", payload_size_bytes=121,
                               attributes={"taskId": "task-1", "msgType": "task-command", "headers": SECRET,
                                           "payload": SECRET, "Authorization": SECRET},
                               error=ErrorInfo(message=SECRET, data=SECRET, stackTrace=SECRET))
        await telemetry.message_emitter.emit(body, correlation_id="session-1")
        row = self.records(telemetry.message_file)[0]
        MessageLogRecord.model_validate(row)
        self.assertEqual(row["correlation_id"], "task-1")
        self.assertEqual(row["body"]["messageId"], "message-1")
        self.assertEqual(row["body"]["eventType"], "send")
        self.assertEqual(row["body"]["attributes"], {"taskId": "task-1", "msgType": "task-command"})
        self.assertNotIn(SECRET, json.dumps(row))

    async def test_receive_requires_validated_message_binding_and_keeps_pairing(self):
        telemetry = self.telemetry()
        body = build_receive_body(system="rabbitmq", exchange="group-1.exchange", virtual_host="acps",
                                  routing_key="", queue_name="group-1.queue", message_id="message-1",
                                  payload_size_bytes=200, delivery_attempt=1,
                                  attributes={"groupId": "group-1", "senderId": PEER, "msgType": "task-command"})
        await telemetry.message_emitter.emit(body, correlation_id="session-1", trace_id=TRACE_ID, span_id=RECEIVE_SPAN)
        self.assertFalse(telemetry.message_file.exists(), "unvalidated raw receive must not be written")
        await telemetry.bind_incoming(command())
        ack = build_settlement_body("ack", system="rabbitmq", exchange="group-1.exchange",
                                    virtual_host="acps", queue_name="group-1.queue", message_id="message-1",
                                    delivery_attempt=1, latency_ms=3)
        await telemetry.message_emitter.emit(ack, correlation_id="session-1", trace_id=TRACE_ID,
                                             span_id=SETTLEMENT_SPAN, parent_span_id=RECEIVE_SPAN)
        rows = self.records(telemetry.message_file)
        self.assertEqual([r["body"]["eventType"] for r in rows], ["receive", "ack"])
        self.assertEqual({r["correlation_id"] for r in rows}, {"task-1"})
        self.assertEqual({r["body"]["messageId"] for r in rows}, {"message-1"})
        self.assertNotIn(SECRET, telemetry.message_file.read_text())

    async def test_receive_identity_mismatch_never_gets_counted(self):
        telemetry = self.telemetry()
        body = build_receive_body(system="rabbitmq", exchange="group-1.exchange", virtual_host="acps",
                                  routing_key="", queue_name="group-1.queue", message_id="message-1",
                                  payload_size_bytes=200, delivery_attempt=1,
                                  attributes={"groupId": "group-other", "senderId": PEER, "msgType": "task-command"})
        await telemetry.message_emitter.emit(body)
        await telemetry.bind_incoming(command())
        self.assertFalse(telemetry.message_file.exists())

    async def test_interleaved_receives_keep_distinct_task_ids(self):
        telemetry = self.telemetry()

        async def receive(i):
            body = build_receive_body(system="rabbitmq", exchange="group-1.exchange", virtual_host="acps",
                                      routing_key="", queue_name="group-1.queue", message_id=f"msg-{i}",
                                      payload_size_bytes=100, delivery_attempt=1,
                                      attributes={"groupId": "group-1", "senderId": PEER, "msgType": "task-command"})
            await telemetry.message_emitter.emit(body)
            await asyncio.sleep(0)
            await telemetry.bind_incoming(command(f"task-{i}", f"msg-{i}"))

        await asyncio.gather(*(receive(i) for i in reversed(range(3))))
        rows = self.records(telemetry.message_file)
        self.assertEqual({r["body"]["messageId"]: r["correlation_id"] for r in rows},
                         {f"msg-{i}": f"task-{i}" for i in range(3)})

    async def test_nack_drops_exception_reason_and_error_body(self):
        telemetry = self.telemetry()
        recv = build_receive_body(system="rabbitmq", exchange="group-1.exchange", virtual_host="acps",
                                 routing_key="", queue_name="group-1.queue", message_id="message-1",
                                 payload_size_bytes=200, delivery_attempt=1,
                                 attributes={"groupId": "group-1", "senderId": PEER, "msgType": "task-command"})
        await telemetry.message_emitter.emit(recv, trace_id=TRACE_ID, span_id=RECEIVE_SPAN)
        await telemetry.bind_incoming(command())
        body = build_settlement_body("nack", system="rabbitmq", exchange="group-1.exchange",
                                    virtual_host="acps", queue_name="group-1.queue", message_id="message-1",
                                    delivery_attempt=1, latency_ms=4, reason=SECRET,
                                    error=ErrorInfo(message=SECRET, data=SECRET))
        await telemetry.message_emitter.emit(body, trace_id=TRACE_ID, span_id=SETTLEMENT_SPAN,
                                             parent_span_id=RECEIVE_SPAN)
        row = self.records(telemetry.message_file)[-1]
        self.assertEqual(row["body"]["eventType"], "nack")
        self.assertEqual(row["body"]["settlement"], {"latencyMs": 4.0})
        self.assertNotIn(SECRET, json.dumps(row))

    async def test_rpc_dispatch_records_error_code_without_body_or_headers(self):
        telemetry = self.telemetry()
        response = RpcResponse(id="rpc-1", error=JSONRPCError(code=-32000, message=SECRET, data=SECRET))
        dispatch = AsyncMock(return_value=response)
        request = RpcRequest(id="rpc-1", params=RpcRequestParams(command=command()))
        observed = await telemetry.wrap_rpc_dispatch(dispatch)(request)
        self.assertIs(observed, response)
        row = self.records(telemetry.access_file)[0]
        AccessLogRecord.model_validate(row)
        self.assertEqual(row["correlation_id"], "task-1")
        self.assertEqual(row["body"]["caller"]["aic"], PEER)
        self.assertEqual(row["body"]["callee"]["aic"], AIC)
        self.assertEqual(row["body"]["error"], {"code": -32000})
        self.assertNotIn(SECRET, json.dumps(row))
        self.assertNotIn("headers", row["body"]["request"])

    async def test_rpc_dispatch_preserves_incoming_trace_parent_for_callee_span(self):
        from amp_telemetry import reset_incoming_traceparent, set_incoming_traceparent
        telemetry = self.telemetry()
        request = RpcRequest(id="rpc-trace", params=RpcRequestParams(command=command()))
        observed = telemetry.wrap_rpc_dispatch(AsyncMock(return_value=RpcResponse(id="rpc-trace")))
        token = set_incoming_traceparent(f"00-{TRACE_ID}-{RECEIVE_SPAN}-01")
        try:
            await observed(request)
        finally:
            reset_incoming_traceparent(token)
        row = self.records(telemetry.access_file)[0]
        self.assertEqual(row["trace_id"], TRACE_ID)
        self.assertEqual(row["parent_span_id"], RECEIVE_SPAN)
        self.assertRegex(row["span_id"], r"^[0-9a-f]{16}$")
        self.assertNotEqual(row["span_id"], RECEIVE_SPAN)

    async def test_dispatch_exception_is_rethrown_without_exception_text_in_log(self):
        telemetry = self.telemetry()
        request = RpcRequest(id="rpc-1", params=RpcRequestParams(command=command()))
        with self.assertRaisesRegex(RuntimeError, SECRET):
            await telemetry.wrap_rpc_dispatch(AsyncMock(side_effect=RuntimeError(SECRET)))(request)
        row = self.records(telemetry.access_file)[0]
        self.assertEqual(row["body"]["response"]["statusCode"], 500)
        self.assertNotIn(SECRET, json.dumps(row))

    async def test_official_sdk_publish_failure_does_not_create_send_record(self):
        from acps_sdk.aip import GroupPartnerMqClient
        telemetry = self.telemetry()
        client = GroupPartnerMqClient(partner_aic=PEER, identity_binding_enabled=False,
                                      message_emitter=telemetry.message_emitter)
        client._exchange_name = "group-1.exchange"
        client._exchange = type("Exchange", (), {"publish": AsyncMock(side_effect=RuntimeError("offline"))})()
        with self.assertRaisesRegex(RuntimeError, "offline"):
            await client._publish_message(command())
        self.assertFalse(telemetry.message_file.exists())
        client._exchange.publish.side_effect = None
        await client._publish_message(command())
        row = self.records(telemetry.message_file)[0]
        self.assertEqual(row["correlation_id"], "task-1")
        self.assertEqual(row["body"]["messageId"], "message-1")
        self.assertNotIn(SECRET, json.dumps(row))

    def test_collection_is_disabled_without_explicit_environment_flag(self):
        from amp_telemetry import telemetry_from_environment
        with patch.dict(os.environ, {}, clear=True):
            self.assertIsNone(telemetry_from_environment(role="leader_rpc", aic=AIC))

    async def test_pending_receive_buffer_is_bounded_and_has_no_raw_payload(self):
        telemetry = self.telemetry()
        for i in range(telemetry.message_emitter.max_pending + 10):
            await telemetry.message_emitter.emit(build_receive_body(
                system="rabbitmq", exchange="group.exchange", virtual_host="acps", routing_key="",
                queue_name="group.queue", message_id=f"message-{i}", payload_size_bytes=100,
                delivery_attempt=1, attributes={"groupId": "group-1", "senderId": PEER, "msgType": "task-command", "payload": SECRET}))
        self.assertLessEqual(telemetry.message_emitter.pending_count, telemetry.message_emitter.max_pending)
        self.assertGreater(telemetry.message_emitter.pending_count, 0)
        self.assertNotIn(SECRET, repr(telemetry.message_emitter._pending))

    async def test_leader_adapter_injects_official_hook_and_binds_validated_callback(self):
        from types import SimpleNamespace
        from mq_group_transport import OfficialMqGroupLeaderAdapter
        telemetry = self.telemetry()
        adapter = OfficialMqGroupLeaderAdapter(leader_aic=AIC, telemetry=telemetry)
        self.assertIs(adapter.group_leader._message_emitter, telemetry.message_emitter)
        client = SimpleNamespace(set_message_handler=lambda handler: setattr(client, "handler", handler))
        adapter.group_leader.group_sessions["session-1"] = SimpleNamespace(group_id="group-1", leader_mq_client=client)
        adapter.group_leader.create_group_session = AsyncMock()
        adapter.group_leader._handle_group_message = AsyncMock()
        await adapter.create_group_and_invite(session_id="session-1", partners=[])
        await telemetry.message_emitter.emit(build_receive_body(
            system="rabbitmq", exchange="group.exchange", virtual_host="acps", routing_key="",
            queue_name="group.queue", message_id="message-1", payload_size_bytes=100,
            delivery_attempt=1, attributes={"groupId": "group-1", "senderId": PEER, "msgType": "task-command"}))
        await client.handler(command())
        adapter.group_leader._handle_group_message.assert_awaited_once()
        self.assertEqual(self.records(telemetry.message_file)[0]["correlation_id"], "task-1")

    async def test_partner_runtime_injects_emitter_into_every_independent_client(self):
        from mq_partner_runtime import OfficialMqPartnerRuntime
        telemetry = self.telemetry()
        runtime = OfficialMqPartnerRuntime(partner_aic=AIC, telemetry=telemetry)
        self.assertIs(runtime._inbox_client._message_emitter, telemetry.message_emitter)
        child = runtime._new_client()
        self.assertIs(child._message_emitter, telemetry.message_emitter)
        await child.close()
        await runtime.close()

    async def test_real_sdk_consumer_authenticates_then_records_receive_and_ack(self):
        from contextlib import asynccontextmanager
        from types import SimpleNamespace
        from acps_sdk.aip import GroupPartnerMqClient
        telemetry = self.telemetry()
        client = GroupPartnerMqClient(partner_aic=AIC, message_emitter=telemetry.message_emitter)
        client._group_id, client._exchange_name, client._queue_name = "group-1", "group-1.exchange", "group-1.queue"
        captured = {}

        async def consume(callback):
            captured["callback"] = callback
            return "test-consumer"

        @asynccontextmanager
        async def process():
            yield

        async def on_command(actual, is_mentioned):
            self.assertTrue(is_mentioned)
            await telemetry.bind_incoming(actual)

        client._queue = SimpleNamespace(consume=consume)
        client.set_command_handler(on_command)
        await client._start_consuming()
        incoming = SimpleNamespace(body=command().model_dump_json().encode(), headers={}, redelivered=False,
                                   routing_key="", process=process, user_id=PEER)
        await captured["callback"](incoming)
        rows = self.records(telemetry.message_file)
        self.assertEqual([r["body"]["eventType"] for r in rows], ["receive", "ack"])
        self.assertEqual({r["correlation_id"] for r in rows}, {"task-1"})
        self.assertNotIn(SECRET, telemetry.message_file.read_text())
        before = telemetry.message_file.read_bytes()
        incoming.user_id = AIC
        with self.assertLogs(level="ERROR"), self.assertRaises(Exception):
            await captured["callback"](incoming)
        self.assertEqual(before, telemetry.message_file.read_bytes(), "identity failure must add no event")
        client._queue = None
        await client.close()

    async def test_identical_message_ids_in_two_groups_keep_their_task_bindings(self):
        telemetry = self.telemetry()
        async def receive(actual):
            group = actual.groupId
            await telemetry.message_emitter.emit(build_receive_body(
                system="rabbitmq", exchange=f"{group}.exchange", virtual_host="acps", routing_key="",
                queue_name=f"{group}.queue", message_id="message-1", payload_size_bytes=100,
                delivery_attempt=1, attributes={"groupId": group, "senderId": PEER, "msgType": "task-command"}))
            await asyncio.sleep(0)
            await telemetry.bind_incoming(actual)
        first, second = command(), command("task-2")
        second.groupId = "group-2"
        await asyncio.gather(receive(second), receive(first))
        rows = self.records(telemetry.message_file)
        self.assertEqual({r["body"]["destination"]["name"]: r["correlation_id"] for r in rows},
                         {"group-1.exchange": "task-1", "group-2.exchange": "task-2"})

    async def test_write_failure_does_not_change_business_result_or_leak_error(self):
        telemetry = self.telemetry()
        request = RpcRequest(id="rpc-1", params=RpcRequestParams(command=command()))
        response = RpcResponse(id="rpc-1", error=JSONRPCError(code=-32000, message=SECRET))
        telemetry._access.emit = AsyncMock(side_effect=OSError(SECRET))
        with self.assertLogs("amp_telemetry", level="WARNING") as captured:
            actual = await telemetry.wrap_rpc_dispatch(AsyncMock(return_value=response))(request)
        self.assertIs(actual, response)
        self.assertNotIn(SECRET, "\n".join(captured.output))

    async def test_receive_age_limit_prevents_late_rebinding(self):
        telemetry = self.telemetry()
        body = build_receive_body(system="rabbitmq", exchange="group-1.exchange", virtual_host="acps",
                                  routing_key="", queue_name="group-1.queue", message_id="message-1",
                                  payload_size_bytes=200, delivery_attempt=1,
                                  attributes={"groupId": "group-1", "senderId": PEER, "msgType": "task-command"})
        await telemetry.message_emitter.emit(body)
        for pending in telemetry.message_emitter._pending.values():
            pending.created_at -= telemetry.message_emitter.retention_seconds + 1
        await telemetry.bind_incoming(command())
        self.assertFalse(telemetry.message_file.exists())

    async def test_no_trace_reused_id_never_falls_back_to_old_settlement(self):
        telemetry = self.telemetry()
        other_peer = "1.2.156.3088.1.BUPT.JSQB3Y.Q9QG7Q.14TNDP.0WSF"

        async def receive(actual):
            await telemetry.message_emitter.emit(build_receive_body(
                system="rabbitmq", exchange="group-1.exchange", virtual_host="acps", routing_key="",
                queue_name="group-1.queue", message_id=actual.id, payload_size_bytes=100,
                delivery_attempt=1, attributes={"groupId": actual.groupId, "senderId": actual.senderId,
                                               "msgType": "task-command"}))
            await telemetry.bind_incoming(actual)

        async def ack(message_id):
            await telemetry.message_emitter.emit(build_settlement_body(
                "ack", system="rabbitmq", exchange="group-1.exchange", virtual_host="acps",
                queue_name="group-1.queue", message_id=message_id, delivery_attempt=1, latency_ms=1))

        await receive(command("task-original", "reused-message"))
        await receive(command("task-independent", "independent-message"))
        conflicting = command("task-conflicting", "reused-message")
        conflicting.senderId = other_peer
        await receive(conflicting)
        await ack("reused-message")
        rows = self.records(telemetry.message_file)
        self.assertFalse(any(r["body"]["eventType"] == "ack" and r["body"]["messageId"] == "reused-message"
                             for r in rows), "ambiguous ACK must not reuse the old task binding")
        await receive(command("task-original", "reused-message"))
        await ack("reused-message")
        await ack("independent-message")
        rows = self.records(telemetry.message_file)
        self.assertEqual([(r["body"]["messageId"], r["correlation_id"]) for r in rows
                          if r["body"]["eventType"] == "ack"], [])
        self.assertFalse(telemetry.message_emitter._bindings)

    async def test_delivery_bindings_are_bounded_and_expire_without_id_fallback(self):
        telemetry = self.telemetry()
        emitter = telemetry.message_emitter
        emitter.max_bindings = 1
        for i in (1, 2):
            actual = command(f"task-{i}", "reused-message")
            await emitter.emit(build_receive_body(
                system="rabbitmq", exchange="group-1.exchange", virtual_host="acps", routing_key="",
                queue_name="group-1.queue", message_id=actual.id, payload_size_bytes=100,
                delivery_attempt=1, attributes={"groupId": "group-1", "senderId": PEER, "msgType": "task-command"}),
                trace_id=TRACE_ID, span_id=f"{i:016x}")
            await telemetry.bind_incoming(actual)
        self.assertEqual(len(emitter._bindings), 1)
        before = telemetry.message_file.read_bytes()
        await emitter.emit(build_settlement_body(
            "ack", system="rabbitmq", exchange="group-1.exchange", virtual_host="acps",
            queue_name="group-1.queue", message_id="reused-message", delivery_attempt=1, latency_ms=1),
            trace_id=TRACE_ID, span_id=SETTLEMENT_SPAN, parent_span_id=f"{1:016x}")
        self.assertEqual(before, telemetry.message_file.read_bytes())
        future = next(iter(emitter._bindings.values())).created_at + emitter.retention_seconds + 1
        with patch("amp_telemetry.monotonic", return_value=future):
            emitter._prune()
        self.assertFalse(emitter._bindings)

    async def sdk_consumer(self, telemetry, on_command=None):
        from contextlib import asynccontextmanager
        from types import SimpleNamespace
        from acps_sdk.aip import GroupPartnerMqClient
        client = GroupPartnerMqClient(partner_aic=AIC, message_emitter=telemetry.message_emitter)
        client._group_id, client._exchange_name, client._queue_name = "group-1", "group-1.exchange", "group-1.queue"
        captured = {}

        async def consume(callback):
            captured["callback"] = callback
            return "test-consumer"

        @asynccontextmanager
        async def process():
            yield

        async def bind(actual, is_mentioned):
            await telemetry.bind_incoming(actual)

        async def cleanup():
            client._queue = None
            await client.close()

        client._queue = SimpleNamespace(consume=consume)
        client.set_command_handler(on_command or bind)
        await client._start_consuming()
        self.addAsyncCleanup(cleanup)

        def incoming(body):
            return SimpleNamespace(body=json.dumps(body).encode(), headers={}, redelivered=False,
                                   routing_key="", process=process, user_id=PEER)
        return captured["callback"], incoming

    async def test_real_sdk_invalid_reused_message_does_not_assign_nack_to_old_task(self):
        telemetry = self.telemetry()
        callback, incoming = await self.sdk_consumer(telemetry)
        valid = command("task-original", "reused-message").model_dump(mode="json")
        await callback(incoming(valid))
        invalid = {**valid, "taskId": "task-invalid", "command": "not-a-valid-command"}
        with self.assertLogs(level="ERROR"), self.assertRaises(Exception):
            await callback(incoming(invalid))
        rows = self.records(telemetry.message_file)
        self.assertEqual([(r["body"]["eventType"], r["correlation_id"]) for r in rows],
                         [("receive", "task-original"), ("ack", "task-original")])

    async def test_real_sdk_concurrent_reused_id_matches_ack_to_each_delivery_span(self):
        telemetry = self.telemetry()
        first_bound, release_first = asyncio.Event(), asyncio.Event()

        async def on_command(actual, is_mentioned):
            await telemetry.bind_incoming(actual)
            if actual.taskId == "task-first":
                first_bound.set()
                await release_first.wait()

        callback, incoming = await self.sdk_consumer(telemetry, on_command)
        first = asyncio.create_task(callback(incoming(command("task-first", "reused-message").model_dump(mode="json"))))
        await first_bound.wait()
        try:
            await callback(incoming(command("task-second", "reused-message").model_dump(mode="json")))
        finally:
            release_first.set()
            await first
        rows = self.records(telemetry.message_file)
        received = {r["span_id"]: (r["trace_id"], r["correlation_id"]) for r in rows
                    if r["body"]["eventType"] == "receive"}
        settled = [r for r in rows if r["body"]["eventType"] == "ack"]
        self.assertEqual([r["correlation_id"] for r in settled], ["task-second", "task-first"])
        for row in settled:
            self.assertEqual(received[row["parent_span_id"]], (row["trace_id"], row["correlation_id"]))


if __name__ == "__main__":
    unittest.main()
