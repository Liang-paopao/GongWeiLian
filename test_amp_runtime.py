"""Offline AMP lifecycle checks; all identities and logs are test fixtures."""
import asyncio
import importlib.util
import json
import os
import signal
import socket
import tempfile
import threading
import unittest
from contextlib import ExitStack, contextmanager, suppress
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


def records(directory):
    return [json.loads(line) for path in Path(directory).glob("amp_heartbeat_*.jsonl")
            for line in path.read_text(encoding="utf-8").splitlines()]


async def wait_for_record(directory, count=1):
    try:
        async with asyncio.timeout(2):
            while len(records(directory)) < count:
                await asyncio.sleep(0.005)
    except TimeoutError:
        raise AssertionError("running service did not write the expected official AMP heartbeat") from None


class AmpRuntimeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.logs = Path(self.temp.name) / "amp"
        self.env = patch.dict(os.environ, {"GONGWEI_AMP_LOG_DIR": str(self.logs),
                                          "GONGWEI_AMP_HEARTBEAT_INTERVAL_SECONDS": "0.025"})
        self.env.start()
        self.addCleanup(self.env.stop)

    def heartbeat_class(self):
        self.assertIsNotNone(importlib.util.find_spec("amp_runtime"), "official AMP lifecycle helper is missing")
        from amp_runtime import AmpHeartbeat
        return AmpHeartbeat

    async def test_only_running_lifecycle_emits_official_schema_and_stops(self):
        heartbeat = self.heartbeat_class()(role="resource", aic="test-resource-aic")
        self.assertFalse(self.logs.exists(), "construction must not emit")
        await heartbeat.start()
        await wait_for_record(self.logs)
        await heartbeat.stop()
        emitted = records(self.logs)
        from acps_sdk.amp.models import HeartbeatLogRecord
        record = HeartbeatLogRecord.model_validate(emitted[0])
        self.assertEqual(record.aic, "test-resource-aic")
        self.assertEqual(emitted[0]["log_type"], "heartbeat")
        self.assertNotIn("observedTimestamp", emitted[0])
        self.assertGreaterEqual(record.body.uptime_seconds, 0)
        await asyncio.sleep(0.06)
        self.assertEqual(records(self.logs), emitted)

    async def test_stop_waits_for_inflight_official_file_write(self):
        heartbeat = self.heartbeat_class()(role="resource", aic="test-resource-aic")
        from acps_sdk.amp import HeartbeatEmitter
        entered, release = threading.Event(), threading.Event()
        original = HeartbeatEmitter._write_line
        def slow_write(emitter, record):
            entered.set()
            release.wait(2)
            original(emitter, record)
        with patch.object(HeartbeatEmitter, "_write_line", new=slow_write):
            await heartbeat.start()
            self.assertTrue(await asyncio.to_thread(entered.wait, 1))
            stopping = asyncio.create_task(heartbeat.stop())
            try:
                await asyncio.sleep(0.02)
                self.assertFalse(stopping.done(), "stop must drain the already running SDK write")
            finally:
                release.set()
                await stopping
        self.assertEqual(len(records(self.logs)), 1)
        stopped = records(self.logs)
        await asyncio.sleep(0.06)
        self.assertEqual(records(self.logs), stopped)

    async def test_connection_loss_pauses_and_recovery_resumes(self):
        from aio_pika import Connection
        # The real aio-pika connected event, rather than a truthy mock, is the gate.
        connection = Connection("amqp://unused.invalid")
        client = SimpleNamespace(connection=connection)
        heartbeat_cls = self.heartbeat_class()
        from amp_runtime import inbox_is_connected
        heartbeat = heartbeat_cls(role="resource", aic="test-resource-aic",
                                  is_ready=lambda: inbox_is_connected(client))
        await heartbeat.start()
        await asyncio.sleep(0.04)
        self.assertEqual(records(self.logs), [])
        connection.connected.set()
        await wait_for_record(self.logs)
        connection.connected.clear()
        await asyncio.sleep(0.01)
        paused = len(records(self.logs))
        await asyncio.sleep(0.06)
        self.assertEqual(len(records(self.logs)), paused)
        connection.connected.set()
        await wait_for_record(self.logs, paused + 1)
        await heartbeat.stop()
        await connection.close()

    async def test_inbox_waits_for_channel_restore_and_pauses_on_channel_only_close(self):
        heartbeat_cls = self.heartbeat_class()
        import amp_runtime
        self.assertTrue(hasattr(amp_runtime, "inbox_is_ready"), "Inbox readiness must include its consumer channel")
        connected, restored = asyncio.Event(), asyncio.Event()
        connected.set()
        channel = SimpleNamespace(is_closed=False, ready=restored.wait)
        client = SimpleNamespace(connection=SimpleNamespace(is_closed=False, connected=connected))
        heartbeat = heartbeat_cls(role="resource", aic="test-resource-aic",
                                  is_ready=lambda: amp_runtime.inbox_is_ready(client, channel))
        await heartbeat.start()
        try:
            await asyncio.sleep(0.06)
            self.assertEqual(records(self.logs), [], "connected before channel restore must not emit")
            restored.set()
            await wait_for_record(self.logs)
            channel.is_closed = True
            restored.clear()
            await asyncio.sleep(0.02)
            paused = len(records(self.logs))
            await asyncio.sleep(0.06)
            self.assertEqual(len(records(self.logs)), paused, "channel-only close must pause while connection stays open")
            channel.is_closed = False
            await asyncio.sleep(0.06)
            self.assertEqual(len(records(self.logs)), paused, "reopened channel must finish restoring its consumer")
            restored.set()
            await wait_for_record(self.logs, paused + 1)
        finally:
            await heartbeat.stop()

    async def test_stop_cancels_waiting_for_inbox_channel_restore(self):
        heartbeat_cls = self.heartbeat_class()
        import amp_runtime
        self.assertTrue(hasattr(amp_runtime, "inbox_is_ready"), "Inbox readiness must include its consumer channel")
        connected, restored = asyncio.Event(), asyncio.Event()
        connected.set()
        channel = SimpleNamespace(is_closed=False, ready=restored.wait)
        client = SimpleNamespace(connection=SimpleNamespace(is_closed=False, connected=connected))
        heartbeat = heartbeat_cls(role="resource", aic="test-resource-aic",
                                  is_ready=lambda: amp_runtime.inbox_is_ready(client, channel))
        await heartbeat.start()
        await asyncio.sleep(0.02)
        await asyncio.wait_for(heartbeat.stop(), 1)
        restored.set()
        await asyncio.sleep(0.06)
        self.assertEqual(records(self.logs), [])

    async def test_each_role_and_identity_uses_its_own_file(self):
        heartbeat_cls = self.heartbeat_class()
        instances = [heartbeat_cls(role=role, aic=aic) for role, aic in
                     (("resource", "aic/one"), ("resource", "aic:one"), ("workorder", "aic/one"))]
        for heartbeat in instances:
            await heartbeat.start()
        await wait_for_record(self.logs, 3)
        for heartbeat in instances:
            await heartbeat.stop()
        files = list(self.logs.glob("amp_heartbeat_*.jsonl"))
        self.assertEqual(len(files), 3)
        for file in files:
            self.assertEqual(len({json.loads(line)["aic"] for line in file.read_text().splitlines()}), 1)

    def test_directory_precedence_and_default_interval(self):
        heartbeat_cls = self.heartbeat_class()
        with patch.dict(os.environ, {}, clear=True):
            from amp_runtime import ROOT
            heartbeat = heartbeat_cls(role="resource", aic="aic")
            self.assertEqual(heartbeat.log_file.parent, ROOT / "logs" / "amp")
            self.assertEqual(heartbeat.interval_seconds, 15)
        with patch.dict(os.environ, {"GONGWEI_LOG_DIR": str(Path(self.temp.name) / "service")}, clear=True):
            heartbeat = heartbeat_cls(role="resource", aic="aic")
            self.assertEqual(heartbeat.log_file.parent, Path(self.temp.name) / "service" / "amp")
        heartbeat = heartbeat_cls(role="resource", aic="aic")
        self.assertEqual(heartbeat.log_file.parent, self.logs)

    def test_invalid_interval_fails_before_any_output(self):
        heartbeat_cls = self.heartbeat_class()
        for interval in ("0", "-1", "nan", "inf", "-inf", "bad", ""):
            with self.subTest(interval=interval), patch.dict(os.environ, {"GONGWEI_AMP_HEARTBEAT_INTERVAL_SECONDS": interval}):
                with self.assertRaisesRegex(ValueError, "interval|间隔"):
                    heartbeat_cls(role="resource", aic="aic")
        self.assertFalse(self.logs.exists())

    async def test_sigterm_fallback_sets_stop_and_restores_handlers(self):
        self.heartbeat_class()
        from amp_runtime import shutdown_signals
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        previous = {sig: signal.getsignal(sig) for sig in (signal.SIGINT, signal.SIGTERM)}
        installed = {}
        with patch.object(loop, "add_signal_handler", side_effect=NotImplementedError), \
                patch("amp_runtime.signal.signal", side_effect=lambda sig, handler: installed.update({sig: handler})):
            with shutdown_signals(stop):
                installed[signal.SIGTERM](signal.SIGTERM, None)
                await asyncio.wait_for(stop.wait(), 1)
            self.assertEqual(installed, previous)


class EntryLifecycleTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.logs = Path(self.temp.name) / "amp"
        self.env = patch.dict(os.environ, {"GONGWEI_AMP_LOG_DIR": str(self.logs),
                                          "GONGWEI_AMP_HEARTBEAT_INTERVAL_SECONDS": "0.025"})
        self.env.start()
        self.addCleanup(self.env.stop)

    async def exercise_inbox(self, module_name, *, failure=False, rejected=False):
        import importlib
        module = importlib.import_module(module_name)
        entered, release = asyncio.Event(), asyncio.Event()
        connected = asyncio.Event()
        connected.set()
        channel = SimpleNamespace(is_closed=False, ready=AsyncMock())
        client = SimpleNamespace(connection=SimpleNamespace(is_closed=False, connected=connected),
                                 ensure_inbox_queue=AsyncMock(return_value=SimpleNamespace(channel=channel)))
        runtime = SimpleNamespace(partner_aic="validated-test-aic", client=client,
                                  set_command_handler=MagicMock(), close=AsyncMock())
        async def start(*args):
            entered.set()
            await release.wait()
            if failure:
                raise RuntimeError("inbox startup failed")
        runtime.start_inbox = start
        leader = SimpleNamespace(runtime=runtime, start=start, close=runtime.close)
        with ExitStack() as stack:
            stack.enter_context(patch.object(module, "get_transport_mode", return_value="platform_mq_inbox"))
            configure = stack.enter_context(patch.object(module, "configure_platform_environment",
                return_value={"aic": runtime.partner_aic, "cert_file": "test.crt"},
                side_effect=RuntimeError("identity rejected") if rejected else None))
            stack.enter_context(patch.object(module, "_runtime_rabbitmq_config", return_value={}))
            if module_name == "run_partner_inbox":
                stack.enter_context(patch.object(module, "OfficialMqPartnerRuntime", return_value=runtime))
                stack.enter_context(patch.object(module, "OfficialMqPartnerHandler", return_value=MagicMock()))
                coroutine = module._run("resource")
            else:
                stack.enter_context(patch.object(module, "_load_env_file"))
                stack.enter_context(patch.object(module, "LeaderInboxRuntime", return_value=leader))
                coroutine = module._run()
            task = asyncio.create_task(coroutine)
            try:
                if rejected:
                    with self.assertRaisesRegex(RuntimeError, "identity rejected"):
                        await task
                    self.assertEqual(records(self.logs), [])
                    return
                await asyncio.wait_for(entered.wait(), 1)
                self.assertEqual(records(self.logs), [], "must wait for Inbox startup success")
                release.set()
                if failure:
                    with self.assertRaisesRegex(RuntimeError, "inbox startup failed"):
                        await task
                    self.assertEqual(records(self.logs), [])
                else:
                    await wait_for_record(self.logs)
                    self.assertEqual(records(self.logs)[0]["aic"], runtime.partner_aic)
            finally:
                if not task.done():
                    task.cancel()
                    with suppress(asyncio.CancelledError):
                        await task
            runtime.close.assert_awaited_once()
            configure.assert_called_once()
            stopped = records(self.logs)
            await asyncio.sleep(0.06)
            self.assertEqual(records(self.logs), stopped)

    async def test_partner_emits_only_after_inbox_ready(self):
        await self.exercise_inbox("run_partner_inbox")

    async def test_partner_start_failure_has_no_heartbeat(self):
        await self.exercise_inbox("run_partner_inbox", failure=True)

    async def test_partner_rejected_identity_has_no_heartbeat(self):
        await self.exercise_inbox("run_partner_inbox", rejected=True)

    async def test_leader_emits_only_after_inbox_ready(self):
        await self.exercise_inbox("run_leader_inbox")

    async def test_leader_start_failure_has_no_heartbeat(self):
        await self.exercise_inbox("run_leader_inbox", failure=True)

    @contextmanager
    def rpc_config(self, *, failure=False):
        import run_leader_rpc as module
        runtime = SimpleNamespace(start=AsyncMock(side_effect=RuntimeError("rpc startup failed") if failure else None),
                                  close=AsyncMock())
        with patch.object(module, "_load_env_file"), \
                patch.object(module, "get_transport_mode", return_value="platform_mq_inbox"), \
                patch.object(module, "configure_platform_environment", return_value={"aic": "validated-leader-aic"}), \
                patch.object(module, "require_mq_configuration"), \
                patch.object(module, "_validate_server_tls", return_value={"certfile": "test.crt", "keyfile": "test.key", "ca_certs": "ca.crt"}), \
                patch.object(module, "LeaderRpcRuntime", return_value=runtime), \
                patch.object(module, "_startup_mq", new=AsyncMock()), \
                patch.object(module, "_shutdown_mq", new=AsyncMock()):
            config = module.build_server_config()
            # Exercise real loopback listeners without any production certificate.
            config.ssl_certfile = config.ssl_keyfile = config.ssl_ca_certs = None
            config.host, config.port = "127.0.0.1", 0
            config.log_config = None
            yield config, runtime

    async def exercise_rpc(self, *, failure=False):
        with self.rpc_config(failure=failure) as (config, runtime):
            app = config.app
            self.assertEqual(records(self.logs), [], "building config must not emit")
            if failure:
                with self.assertRaisesRegex(RuntimeError, "rpc startup failed"):
                    async with app.router.lifespan_context(app):
                        self.fail("failed startup cannot yield")
                self.assertEqual(records(self.logs), [])
            else:
                async with app.router.lifespan_context(app):
                    runtime.start.assert_awaited_once()
                    await asyncio.sleep(0.06)
                    self.assertEqual(records(self.logs), [], "lifespan alone does not establish a listener")
                stopped = records(self.logs)
                await asyncio.sleep(0.06)
                self.assertEqual(records(self.logs), stopped)
        runtime.close.assert_awaited_once()

    async def test_rpc_lifespan_without_listener_does_not_emit(self):
        await self.exercise_rpc()

    async def test_rpc_failed_lifespan_has_no_heartbeat(self):
        await self.exercise_rpc(failure=True)

    async def listener_server(self, config):
        import run_leader_rpc as module
        server_type = getattr(module, "LeaderRpcServer", module.uvicorn.Server)
        server = server_type(config)
        config.load()
        server.lifespan = config.lifespan_class(config)
        return server

    async def test_rpc_waits_for_real_listener_and_stops_before_shutdown_drains(self):
        with self.rpc_config() as (config, runtime):
            server = await self.listener_server(config)
            loop = asyncio.get_running_loop()
            create_server = loop.create_server
            async def delayed_bind(*args, **kwargs):
                await asyncio.sleep(0.06)
                self.assertEqual(records(self.logs), [], "binding is not yet complete")
                return await create_server(*args, **kwargs)
            async def slow_drain():
                snapshot = records(self.logs)
                await asyncio.sleep(0.06)
                self.assertEqual(records(self.logs), snapshot, "closed listener must not emit while requests drain")
            try:
                with patch.object(loop, "create_server", new=delayed_bind):
                    await server.startup()
                self.assertTrue(server.started)
                self.assertTrue(all(listener.is_serving() for listener in server.servers))
                await wait_for_record(self.logs)
                self.assertEqual(records(self.logs)[0]["aic"], "validated-leader-aic")
            finally:
                if server.started:
                    with patch.object(server, "_wait_tasks_to_complete", new=slow_drain):
                        await server.shutdown()
                else:
                    await server.lifespan.shutdown()
            snapshot = records(self.logs)
            await asyncio.sleep(0.06)
            self.assertEqual(records(self.logs), snapshot)
        runtime.close.assert_awaited_once()

    async def test_rpc_occupied_port_never_emits_heartbeat(self):
        with self.rpc_config() as (config, runtime), socket.socket() as occupied:
            occupied.bind(("127.0.0.1", 0))
            occupied.listen()
            config.port = occupied.getsockname()[1]
            server = await self.listener_server(config)
            loop = asyncio.get_running_loop()
            create_server = loop.create_server
            async def delayed_bind(*args, **kwargs):
                await asyncio.sleep(0.06)
                return await create_server(*args, **kwargs)
            with patch.object(loop, "create_server", new=delayed_bind):
                with self.assertRaises(SystemExit):
                    await server.startup()
            self.assertFalse(server.started)
            self.assertEqual(records(self.logs), [], "failed socket binding must not advertise liveness")
        runtime.close.assert_awaited_once()

    async def test_rpc_serve_exception_stops_heartbeat_even_without_normal_shutdown(self):
        with self.rpc_config() as (config, runtime):
            server = await self.listener_server(config)
            async def fail_main_loop():
                await wait_for_record(self.logs)
                raise RuntimeError("server loop failed")
            try:
                with patch.object(server, "main_loop", new=fail_main_loop):
                    with self.assertRaisesRegex(RuntimeError, "server loop failed"):
                        await server.serve()
                snapshot = records(self.logs)
                await asyncio.sleep(0.06)
                self.assertEqual(records(self.logs), snapshot, "serve failure must stop its heartbeat task")
            finally:
                if server.started:
                    await server.shutdown()
        runtime.close.assert_awaited_once()


class InboxLogDirectoryTests(unittest.TestCase):
    def test_inbox_entrypoints_create_log_in_configured_nested_directory(self):
        import run_leader_inbox
        import run_partner_inbox
        for module, filename, args in ((run_leader_inbox, "leader_inbox_runtime.log", ()),
                                       (run_partner_inbox, "resource_partner_inbox.log", (["--role", "resource"],))):
            with self.subTest(module=module.__name__), tempfile.TemporaryDirectory() as temp, \
                    patch.dict(os.environ, {"GONGWEI_LOG_DIR": str(Path(temp) / "nested" / "logs")}), \
                    patch.object(module.logging, "basicConfig") as configure, \
                    patch.object(module.asyncio, "run", side_effect=lambda coroutine: coroutine.close()), \
                    patch.object(run_leader_inbox, "_load_env_file"):
                try:
                    self.assertEqual(module.main(*args), 0)
                    self.assertTrue((Path(temp) / "nested" / "logs" / filename).is_file())
                finally:
                    if configure.call_args:
                        for handler in configure.call_args.kwargs["handlers"]:
                            handler.close()


if __name__ == "__main__":
    unittest.main()
