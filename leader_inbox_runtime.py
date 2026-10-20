"""Official ACPs Inbox runtime for the externally callable Leader role.

The Leader is also a GroupPartner from the caller's point of view.  This
runtime intentionally delegates wire handling to ``GroupPartnerMqClient``;
local HTTP remains a separate transport used by the browser and tests.
"""
from __future__ import annotations

import json
import logging
import uuid
from typing import Any, Awaitable, Callable

from acps_sdk.aip import Product, TaskCommand, TaskCommandType, TaskState, TextDataItem
from agentic_core import create_conversation
from stage2_db import connect_db
from mq_group_transport import OfficialMqPartnerRuntime
from local_log import record

logger = logging.getLogger(__name__)


class LeaderInboxRuntime:
    def __init__(self, *, leader_aic: str, rabbitmq_config: dict[str, Any], command_handler: Callable[[TaskCommand], Awaitable[dict[str, Any]]]):
        self.leader_aic = leader_aic
        self.command_handler = command_handler
        self.runtime = OfficialMqPartnerRuntime(partner_aic=leader_aic, rabbitmq_config=rabbitmq_config)
        self.states: dict[tuple[str, str], str] = {}

    async def start(self) -> None:
        self.runtime.set_command_handler(self._handle_command)
        await self.runtime.start_inbox(lambda invitation: self._record_invitation(invitation))
        logger.info("event=leader_inbox_listening leader_aic=%s", self.leader_aic)

    async def _record_invitation(self, invitation: Any) -> None:
        logger.info("event=leader_inbox_invitation_received group_id=%s leader_aic=%s", getattr(invitation.group, "groupId", ""), getattr(invitation.group.leader, "aic", ""))

    async def _handle_command(self, command: TaskCommand, is_mentioned: bool = True) -> None:
        if not is_mentioned:
            return
        key = (command.sessionId or "", command.taskId or "")
        session_id = command.sessionId or ""
        task_id = command.taskId or ""
        message_id = command.id
        try:
            if not all((session_id.strip(), task_id.strip(), command.senderId.strip(), message_id.strip())):
                raise ValueError("Inbox 命令必须包含 sessionId、taskId、senderId 和 message id。")
            create_conversation(
                session_id=session_id, task_id=task_id,
                protocol_owner={"entrypoint": "mq_inbox", "sender_id": command.senderId.strip().upper()},
                allow_create=command.command == TaskCommandType.Start,
            )
            with connect_db() as db:
                task_status = db.execute("SELECT status FROM agent_tasks WHERE task_id=?", (task_id,)).fetchone()[0]
            if task_status not in {"completed", "cancelled"}:
                self.states[key] = "accepted"
                await self.runtime.client.send_task_result(task_id, session_id, TaskState.Accepted)
                self.states[key] = "working"
                await self.runtime.client.send_task_result(task_id, session_id, TaskState.Working)
            result = await self.command_handler(command)
            state_name = result.get("state", "awaiting_completion")
            state = {
                "awaiting_input": TaskState.AwaitingInput,
                "awaiting_completion": TaskState.AwaitingCompletion,
                "completed": TaskState.Completed,
                "canceled": TaskState.Canceled,
                "cancelled": TaskState.Canceled,
                "failed": TaskState.Failed,
            }.get(state_name, TaskState.AwaitingCompletion)
            products = None
            if result.get("result") is not None or state in {TaskState.AwaitingInput, TaskState.AwaitingCompletion, TaskState.Completed}:
                products = [Product(
                    id=f"leader-result-{uuid.uuid4()}",
                    name="gongwei-leader-result",
                    dataItems=[TextDataItem(text=json.dumps(result.get("result", result), ensure_ascii=False))],
                )]
            status_items = None
            if result.get("question"):
                status_items = [TextDataItem(text=str(result["question"]))]
            elif state is TaskState.Failed and result.get("error"):
                status_items = [TextDataItem(text=str(result["error"]))]
            await self.runtime.client.send_task_result(task_id, session_id, state, products=products, status_data_items=status_items)
            self.states[key] = state.value
            record("leader_inbox", "task_result", {"session_id": session_id, "task_id": task_id, "message_id": message_id, "state": state.value})
            logger.info("event=leader_inbox_task_result session_id=%s task_id=%s message_id=%s state=%s", session_id, task_id, message_id, state.value)
        except Exception as exc:
            self.states[key] = "failed"
            with_context = {"session_id": session_id, "task_id": task_id, "message_id": message_id, "error": type(exc).__name__}
            with_context["reason"] = str(exc)
            record("leader_inbox", "task_failed", with_context)
            try:
                await self.runtime.client.send_task_result(
                    task_id,
                    session_id,
                    TaskState.Failed,
                    status_data_items=[TextDataItem(text="Leader 处理失败：" + str(exc))],
                )
            except Exception:
                logger.exception("event=leader_inbox_failed_result_send session_id=%s task_id=%s", session_id, task_id)
            logger.error("event=leader_inbox_task_failed session_id=%s task_id=%s message_id=%s error=%s", session_id, task_id, message_id, type(exc).__name__)
            raise

    async def close(self) -> None:
        await self.runtime.close()
