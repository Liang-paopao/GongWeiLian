"""Durable official AIP RPC entry; business Partner calls remain MQ-only.

Run one process per protocol database. Pending commands survive shutdown and
are replayed with the same IDs; Partner operations must retain their business
idempotency keys. The SDK validates TLS identity before calling this dispatcher.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import os
import sqlite3
import uuid
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import FastAPI, Request
from acps_sdk.aip import Product, TaskCommand, TaskCommandType, TaskResult, TaskState, TextDataItem
from acps_sdk.aip.aip_base_model import TaskStatus
from acps_sdk.aip.aip_peer_cert import AipPeerCertificateMiddleware
from acps_sdk.aip.aip_rpc_model import JSONRPCError, RpcRequest, RpcResponse
from acps_sdk.aip.aip_rpc_server import CommandHandlers, DefaultHandlers, handle_rpc_request

from agentic_core import create_conversation
from leader_external_flow import cancellation_requested, compensate_external_failure, handle_external_command, is_explicit_cancellation, is_explicit_confirmation, register_compensation
from stage2_db import connect_db, initialize_database, transaction
from stage2_domain import DomainError, now_utc
from plan_continuation import explicit_reference, owns_protocol_task
from leader_external_flow import _payload
from amp_telemetry import reset_incoming_traceparent, set_incoming_traceparent, telemetry_from_environment

logger = logging.getLogger(__name__)
TERMINAL = {TaskState.Completed, TaskState.Canceled, TaskState.Failed, TaskState.Rejected}
SCHEMA = """
CREATE TABLE IF NOT EXISTS rpc_sessions (
 session_id TEXT PRIMARY KEY, owner TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS rpc_tasks (
 task_id TEXT PRIMARY KEY, session_id TEXT NOT NULL, owner TEXT NOT NULL,
 snapshot_json TEXT NOT NULL, pending_json TEXT, cancel_json TEXT, rollback_json TEXT
);
CREATE TABLE IF NOT EXISTS rpc_receipts (
 owner TEXT NOT NULL, message_id TEXT NOT NULL, fingerprint TEXT NOT NULL,
 task_id TEXT NOT NULL, PRIMARY KEY(owner, message_id)
);
"""


class LeaderRpcRuntime:
    """Persist protocol snapshots without the SDK's global in-memory TaskManager."""

    def __init__(self, *, leader_aic: str, state_path: str | Path,
                 command_handler: Callable[[TaskCommand], Awaitable[dict[str, Any]]] = handle_external_command,
                 compensation_retry_seconds: float = 5.0,
                 cancel_response_timeout_seconds: float = 1.0):
        if not leader_aic.strip():
            raise ValueError("Leader AIC is required")
        if not math.isfinite(cancel_response_timeout_seconds) or cancel_response_timeout_seconds <= 0:
            raise ValueError("Cancel response timeout must be finite positive seconds")
        self.leader_aic = leader_aic
        self.state_path = Path(state_path).resolve()
        self.command_handler = command_handler
        self.compensation_retry_seconds = max(0.01, compensation_retry_seconds)
        self.cancel_response_timeout_seconds = cancel_response_timeout_seconds
        self._process_lock = None
        self._jobs: dict[str, asyncio.Task] = {}
        self._plan_locks: dict[str, asyncio.Lock] = {}
        self._lock = asyncio.Lock()
        self._closed = False

    @contextmanager
    def _db(self):
        connection = sqlite3.connect(self.state_path, timeout=10)
        connection.row_factory = sqlite3.Row
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    async def start(self) -> None:
        if self._process_lock is not None:
            return
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        self._acquire_process_lock()
        try:
            initialize_database()
            with self._db() as db:
                db.execute("PRAGMA journal_mode=WAL")
                db.executescript(SCHEMA)
                columns = {row[1] for row in db.execute("PRAGMA table_info(rpc_tasks)")}
                for name in ("cancel_json", "rollback_json"):
                    if name not in columns:
                        db.execute(f"ALTER TABLE rpc_tasks ADD COLUMN {name} TEXT")
                pending = db.execute("SELECT pending_json FROM rpc_tasks WHERE pending_json IS NOT NULL").fetchall()
        except BaseException:
            self._process_lock.close()
            self._process_lock = None
            raise
        self._closed = False
        for row in pending:
            self._schedule(TaskCommand.model_validate_json(row["pending_json"]))

    def _acquire_process_lock(self) -> None:
        # Hold an OS lock throughout the runtime lifetime; process exit releases
        # it automatically. Never unlink the lock file (that would create races).
        handle = open(str(self.state_path) + ".lock", "a+b")
        try:
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            handle.close()
            raise RuntimeError("Leader RPC state database is already occupied by another runtime") from exc
        self._process_lock = handle

    def _schedule(self, command: TaskCommand) -> None:
        task_id = command.taskId
        if task_id not in self._jobs or self._jobs[task_id].done():
            job = asyncio.create_task(self._execute(command), name=f"leader-rpc-{task_id}")
            self._jobs[task_id] = job
            def finished(done):
                if self._jobs.get(task_id) is done:
                    self._jobs.pop(task_id, None)
                if not done.cancelled() and done.exception() is not None:
                    logger.error("event=leader_rpc_storage_failure task_id=%s error=%s", task_id, type(done.exception()).__name__)
            job.add_done_callback(finished)

    @staticmethod
    def _error(request: RpcRequest, code: int, message: str) -> RpcResponse:
        return RpcResponse(id=request.id, error=JSONRPCError(code=code, message=message))

    @staticmethod
    def _transition(task: TaskResult, state: TaskState, text: str | None = None) -> None:
        status = TaskStatus(state=state, stateChangedAt=now_utc(), dataItems=[TextDataItem(text=text)] if text else [])
        task.status = status
        task.statusHistory = [*(task.statusHistory or []), status]
        task.sentAt = now_utc()

    def _save(self, task: TaskResult, *, clear_pending: bool = False) -> None:
        with self._db() as db:
            if clear_pending:
                db.execute("UPDATE rpc_tasks SET snapshot_json=?,pending_json=NULL,cancel_json=NULL,rollback_json=NULL WHERE task_id=?", (task.model_dump_json(), task.taskId))
            else:
                db.execute("UPDATE rpc_tasks SET snapshot_json=? WHERE task_id=?", (task.model_dump_json(), task.taskId))

    async def dispatch_request(self, request: RpcRequest) -> RpcResponse:
        """Called only after handle_rpc_request has bound senderId to TLS CN."""
        command = request.params.command.model_copy(deep=True)
        if not command.sessionId or not command.senderId or not command.id:
            return self._error(request, -32602, "sessionId, senderId and message id are required")
        if self._closed:
            return self._error(request, -32000, "Leader is shutting down; retry this message")
        if command.command not in {TaskCommandType.Start, TaskCommandType.Get, TaskCommandType.Continue, TaskCommandType.Complete, TaskCommandType.Cancel}:
            return self._error(request, -32602, "Unsupported command")
        owner = command.senderId.strip().upper()
        fingerprint = hashlib.sha256(json.dumps(command.model_dump(mode="json"), sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        async with self._lock:
            with self._db() as db:
                session = db.execute("SELECT owner FROM rpc_sessions WHERE session_id=?", (command.sessionId,)).fetchone()
                if session and session["owner"] != owner:
                    return self._error(request, -32009, "Session access denied")
                receipt = db.execute("SELECT * FROM rpc_receipts WHERE owner=? AND message_id=?", (owner, command.id)).fetchone()
                if receipt:
                    if receipt["fingerprint"] != fingerprint:
                        return self._error(request, -32602, "Message id was already used for a different command")
                    row = db.execute("SELECT * FROM rpc_tasks WHERE task_id=?", (receipt["task_id"],)).fetchone()
                    return RpcResponse(id=request.id, result=TaskResult.model_validate_json(row["snapshot_json"]))
                row = db.execute("SELECT * FROM rpc_tasks WHERE task_id=?", (command.taskId,)).fetchone() if command.taskId else None
                if row and (row["owner"] != owner or row["session_id"] != command.sessionId):
                    return self._error(request, -32009, "Task access denied")
                task = TaskResult.model_validate_json(row["snapshot_json"]) if row else None
                if task is None and command.command != TaskCommandType.Start:
                    return self._error(request, -32001, "Task not found")
                if command.command == TaskCommandType.Get:
                    return RpcResponse(id=request.id, result=await DefaultHandlers.get(command, task))
                if task is not None and (command.command == TaskCommandType.Start or task.status.state in TERMINAL):
                    db.execute("INSERT INTO rpc_receipts VALUES(?,?,?,?)", (owner, command.id, fingerprint, task.taskId))
                    return RpcResponse(id=request.id, result=task)
                if row and row["pending_json"] is not None:
                    if is_explicit_cancellation(command):
                        task.status.dataItems = [TextDataItem(text="取消请求已接收，将在当前业务步骤后安全取消。")]
                        task.commandHistory = [*(task.commandHistory or []), command]
                        db.execute("UPDATE rpc_tasks SET snapshot_json=?,cancel_json=COALESCE(cancel_json,?) WHERE task_id=?", (task.model_dump_json(), command.model_dump_json(), task.taskId))
                        db.execute("INSERT INTO rpc_receipts VALUES(?,?,?,?)", (owner, command.id, fingerprint, task.taskId))
                        return RpcResponse(id=request.id, result=task)
                    return self._error(request, -32010, "Task is working; get its result before sending another command")
                if task is None:
                    command.taskId = command.taskId or f"task-{uuid.uuid4()}"
                    # A new protocol caller cannot adopt a pre-existing browser
                    # or Inbox task/session merely by guessing its public ID.
                    with connect_db() as business:
                        collision = business.execute("SELECT 1 FROM agent_tasks WHERE task_id=?", (command.taskId,)).fetchone()
                        session_collision = business.execute("SELECT 1 FROM agent_sessions WHERE session_id=?", (command.sessionId,)).fetchone() if session is None else None
                    if collision or session_collision:
                        return self._error(request, -32009, "Task or session already belongs to another entry point")
                    initial = TaskStatus(state=TaskState.Accepted, stateChangedAt=now_utc(), dataItems=[])
                    task = TaskResult(id=f"result-{uuid.uuid4()}", sentAt=now_utc(), senderRole="partner", senderId=self.leader_aic,
                                      sessionId=command.sessionId, taskId=command.taskId, status=initial,
                                      statusHistory=[initial], commandHistory=[command])
                    db.execute("INSERT OR IGNORE INTO rpc_sessions VALUES(?,?)", (command.sessionId, owner))
                    db.execute("INSERT INTO rpc_tasks(task_id,session_id,owner,snapshot_json,pending_json) VALUES(?,?,?,?,?)", (task.taskId, command.sessionId, owner, task.model_dump_json(), command.model_dump_json()))
                else:
                    has_text = any(isinstance(item, TextDataItem) and item.text.strip() for item in command.dataItems or [])
                    task.commandHistory = [*(task.commandHistory or []), command]
                    if (command.command == TaskCommandType.Complete and not is_explicit_confirmation(command)) or (command.command == TaskCommandType.Continue and not has_text):
                        db.execute("UPDATE rpc_tasks SET snapshot_json=? WHERE task_id=?", (task.model_dump_json(), task.taskId))
                        db.execute("INSERT INTO rpc_receipts VALUES(?,?,?,?)", (owner, command.id, fingerprint, task.taskId))
                        return RpcResponse(id=request.id, result=task)
                    self._transition(task, TaskState.Accepted)
                    db.execute("UPDATE rpc_tasks SET snapshot_json=?,pending_json=? WHERE task_id=?", (task.model_dump_json(), command.model_dump_json(), task.taskId))
                db.execute("INSERT INTO rpc_receipts VALUES(?,?,?,?)", (owner, command.id, fingerprint, task.taskId))
            self._schedule(command)
            if command.command != TaskCommandType.Cancel:
                return RpcResponse(id=request.id, result=task)
            cancel_job = self._jobs[task.taskId]

        # The official cancel client consumes this response without polling.
        # Wait only for this idle task's existing worker, outside the dispatch
        # lock. A timeout or disconnected caller must not cancel compensation.
        try:
            await asyncio.wait_for(asyncio.shield(cancel_job), self.cancel_response_timeout_seconds)
        except TimeoutError:
            pass
        with self._db() as db:
            row = db.execute("SELECT snapshot_json FROM rpc_tasks WHERE task_id=?", (task.taskId,)).fetchone()
        return RpcResponse(id=request.id, result=TaskResult.model_validate_json(row["snapshot_json"]))

    async def _execute(self, command: TaskCommand) -> None:
        payload = _payload(command)
        reference = explicit_reference(str(payload.get('text') or payload.get('message') or ''))
        if reference is None:
            with connect_db() as business:
                row = business.execute('SELECT context_json FROM agent_tasks WHERE task_id=?', (command.taskId,)).fetchone()
            if row:
                context = json.loads(row['context_json'])
                reference = (context.get('confirmation_offer') or context.get('plan_continuation') or {}).get('reference')
        if reference:
            async with self._plan_locks.setdefault(reference, asyncio.Lock()):
                await self._execute_serial(command)
        else:
            await self._execute_serial(command)

    async def _execute_serial(self, command: TaskCommand) -> None:
        while not self._closed:
            if await self._execute_attempt(command):
                return
            await asyncio.sleep(self.compensation_retry_seconds)

    async def _execute_attempt(self, command: TaskCommand) -> bool:
        with self._db() as db:
            row = db.execute("SELECT snapshot_json FROM rpc_tasks WHERE task_id=?", (command.taskId,)).fetchone()
        task = TaskResult.model_validate_json(row["snapshot_json"])
        if task.status.state != TaskState.Working:
            self._transition(task, TaskState.Working)
            self._save(task)
        cancellation_context = cancellation_requested.set(lambda: self._queued_cancel(command.taskId) is not None)
        compensation_context = register_compensation.set(lambda plan_id: self._register_compensation(command.taskId, plan_id))
        ownership_context = owns_protocol_task.set(lambda source: self._owns_task(command, source))
        retry = False
        try:
            create_conversation(session_id=command.sessionId, task_id=command.taskId)
            result, failure = None, None
            if self._queued_cancel(command.taskId) is None and self._pending_compensation(command.taskId) is None:
                try:
                    result = await self.command_handler(command)
                except Exception as exc:
                    failure = exc
            cancel = self._queued_cancel(command.taskId)
            if cancel is not None:
                # Run cancellation sequentially after the current operation;
                # no competing worker can overwrite the resulting terminal state.
                cancellation_requested.set(lambda: False)
                if not any(item.id == cancel.id for item in task.commandHistory or []):
                    task.commandHistory = [*(task.commandHistory or []), cancel]
                result = await self.command_handler(cancel)
                if result.get("state") in {"failed", "rejected"}:
                    raise RuntimeError("Cancellation compensation has not completed")
            elif (rollback := self._pending_compensation(command.taskId)) is not None:
                result = await compensate_external_failure(command, rollback["plan_id"])
            elif failure is not None:
                raise failure
            # A cancellation can arrive while a rollback network request is
            # in flight. Re-read the durable intent after the await before
            # committing any terminal snapshot or clearing the pending work.
            if cancel is None and (cancel := self._queued_cancel(command.taskId)) is not None:
                cancellation_requested.set(lambda: False)
                if not any(item.id == cancel.id for item in task.commandHistory or []):
                    task.commandHistory = [*(task.commandHistory or []), cancel]
                result = await self.command_handler(cancel)
            state = TaskState(str(result.get("state", "awaiting_input")).replace("_", "-"))
            business_cancellation_completed = (
                command.command == TaskCommandType.Start and cancel is None
                and state == TaskState.Completed
                and (result.get("result") or {}).get("status") == "cancelled"
                and bool((result.get("result") or {}).get("cancellationContinuation"))
            )
            if is_explicit_cancellation(command) or cancel is not None:
                if state in {TaskState.Failed, TaskState.Rejected}:
                    raise RuntimeError("Cancellation compensation has not completed")
                if (result.get("result") or {}).get("status") != "completed" and not business_cancellation_completed:
                    state = TaskState.Canceled
            if state == TaskState.Canceled and (result.get("result") or {}).get("cancellationContinuation"):
                # A genuine protocol cancellation can preempt a completed
                # business operation before its RPC result commits. Preserve
                # that decision for direct/Inbox replay of the same task too.
                with transaction() as business:
                    row = business.execute("SELECT context_json FROM agent_tasks WHERE task_id=?", (command.taskId,)).fetchone()
                    context = json.loads(row["context_json"]) if row else {}
                    if context.get("cancellation_continuation"):
                        context["cancellation_protocol_canceled"] = True
                        business.execute("UPDATE agent_tasks SET context_json=? WHERE task_id=?", (json.dumps(context, ensure_ascii=False), command.taskId))
            self._transition(task, state, result.get("question") or result.get("error") or result.get("summary"))
            task.products = [Product(id=f"leader-product-{task.taskId}", name="gongwei-leader-result",
                                     dataItems=[TextDataItem(text=json.dumps(result.get("result", result), ensure_ascii=False))])]
        except asyncio.CancelledError:
            # Leave the pending command durable for restart, never pretend that
            # cancellation of the process canceled the user's business task.
            raise
        except Exception as exc:
            retry = is_explicit_cancellation(command) or self._queued_cancel(command.taskId) is not None or self._pending_compensation(command.taskId) is not None
            if retry:
                logger.warning("event=leader_rpc_compensation_pending task_id=%s error=%s", command.taskId, type(exc).__name__)
                notice = "资源释放尚未确认，取消或失败补偿已保存，将自动重试。"
                if not any(isinstance(item, TextDataItem) and item.text == notice for item in task.status.dataItems or []):
                    self._transition(task, TaskState.Working, notice)
            else:
                logger.warning("event=leader_rpc_task_failed task_id=%s error=%s", command.taskId, type(exc).__name__)
                # Known business errors contain user-facing validation and
                # discovery reasons. Never echo arbitrary SDK/HTTP exceptions,
                # which can contain transport credentials or headers.
                reason = str(exc)[:500] if isinstance(exc, DomainError) else f"Leader 处理失败（{type(exc).__name__}），请按任务编号检查服务日志。"
                self._transition(task, TaskState.Failed, reason)
        finally:
            cancellation_requested.reset(cancellation_context)
            register_compensation.reset(compensation_context)
            owns_protocol_task.reset(ownership_context)
        self._save(task, clear_pending=not retry)
        return not retry

    def _owns_task(self, command: TaskCommand, task_id: str) -> bool:
        with self._db() as db:
            row = db.execute('SELECT owner,session_id FROM rpc_tasks WHERE task_id=?', (task_id,)).fetchone()
        return bool(row and row['owner'] == command.senderId.strip().upper() and row['session_id'] == command.sessionId)

    def _register_compensation(self, task_id: str, plan_id: str) -> None:
        with self._db() as db:
            db.execute("UPDATE rpc_tasks SET rollback_json=? WHERE task_id=?", (json.dumps({"plan_id": plan_id}), task_id))

    def _pending_compensation(self, task_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute("SELECT rollback_json FROM rpc_tasks WHERE task_id=?", (task_id,)).fetchone()
        return json.loads(row["rollback_json"]) if row and row["rollback_json"] else None

    def _queued_cancel(self, task_id: str) -> TaskCommand | None:
        with self._db() as db:
            row = db.execute("SELECT cancel_json FROM rpc_tasks WHERE task_id=?", (task_id,)).fetchone()
        return TaskCommand.model_validate_json(row["cancel_json"]) if row and row["cancel_json"] else None

    async def wait_idle(self) -> None:
        """Drain accepted work (useful for a local supervisor and offline tests)."""
        if self._jobs:
            await asyncio.gather(*list(self._jobs.values()))

    async def close(self) -> None:
        self._closed = True
        jobs = list(self._jobs.values())
        for job in jobs:
            job.cancel()
        if jobs:
            await asyncio.gather(*jobs, return_exceptions=True)
        self._jobs.clear()
        if self._process_lock is not None:
            self._process_lock.close()
            self._process_lock = None


def create_app(runtime: LeaderRpcRuntime, *, startup: Callable[[], Awaitable[None]] | None = None,
               shutdown: Callable[[], Awaitable[None]] | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app):
        try:
            if startup:
                await startup()
            await runtime.start()
            yield
        finally:
            await runtime.close()
            if shutdown:
                await shutdown()

    app = FastAPI(title="Gongwei Leader AIP RPC", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(AipPeerCertificateMiddleware)
    telemetry = telemetry_from_environment(role="leader_rpc", aic=runtime.leader_aic) if os.environ.get("GONGWEI_AMP_METADATA_ENABLED") == "1" else None

    @app.post("/rpc", response_model=RpcResponse)
    async def rpc(request: Request):
        dispatch = telemetry.wrap_rpc_dispatch(runtime.dispatch_request) if telemetry else runtime.dispatch_request
        trace_token = set_incoming_traceparent(request.headers.get("traceparent")) if telemetry else None
        try:
            return await handle_rpc_request(request, CommandHandlers(), local_aic=runtime.leader_aic,
                                            identity_binding_enabled=True, dispatch_request=dispatch)
        finally:
            if trace_token is not None:
                reset_incoming_traceparent(trace_token)

    return app
