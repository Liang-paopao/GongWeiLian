"""Leader API and served-page contract tests; partner calls are covered by integration tests."""
from __future__ import annotations

import os
import tempfile
import sqlite3
import unittest
from unittest.mock import patch
from datetime import date, timedelta
from pathlib import Path

from fastapi.testclient import TestClient


class Stage2ApiTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        os.environ["GONGWEI_STAGE2_DB"] = str(Path(self.temp.name) / "stage2.db")
        import web_app
        self.web_app = web_app
        self.client = TestClient(web_app.app, client=("127.0.0.1", 50002))
        self.date = (date.today() + timedelta(days=1)).isoformat()

    def tearDown(self):
        os.environ.pop("GONGWEI_STAGE2_DB", None)
        self.temp.cleanup()

    def test_health_and_bootstrap_expose_simulated_boundary(self):
        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertFalse(health.json()["platform_verified"])
        bootstrap = self.client.get("/api/bootstrap")
        self.assertEqual(bootstrap.status_code, 200)
        self.assertTrue(bootstrap.json()["simulated_data"])
        self.assertEqual(len(bootstrap.json()["pumps"]), 3)

    def test_inventory_adjustment_endpoint_updates_resource_quantity(self):
        response = self.client.post("/api/resources/inventory/tool-inspection-kit/adjust", json={"delta": 1})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["item"]["available_qty"], 6)
        self.assertEqual(body["item"]["total_qty"], 6)
        invalid = self.client.post("/api/resources/inventory/tool-inspection-kit/adjust", json={"delta": -7})
        self.assertEqual(invalid.status_code, 400)

    def test_aip_calls_reads_the_active_log_directory(self):
        import local_log
        with patch.object(local_log, 'LOG_DIR', Path(self.temp.name) / 'active-logs'):
            local_log.record('stage2_leader', 'aip_response', {'partner': 'resource', 'task_id': 'audit-current-run'})
            response = self.client.get('/api/aip-calls')
        self.assertEqual(response.status_code, 200)
        self.assertEqual([row['task_id'] for row in response.json()], ['audit-current-run'])

    def test_create_missing_request_returns_awaiting_input(self):
        response = self.client.post("/api/inspection-requests", json={"pump_id": "pump-001"})
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["status"], "awaiting_input")
        self.assertIn("work_date", body["missing_fields"])

    def test_structured_text_request_aliases_work_without_audio(self):
        response = self.client.post("/api/inspection-requests", json={
            "device_id": "pump-001",
            "anomaly_description": "运行声音比平时更粗",
            "work_date": self.date,
            "preferred_time": "10:30",
            "duration": 45,
            "urgency": "high",
            "required_skill": "pump_inspection",
            "required_tools": ["tool-inspection-kit"],
        })
        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body["status"], "draft")
        self.assertEqual(body["pump_id"], "pump-001")
        self.assertEqual(body["start_time"], "10:30")
        self.assertEqual(body["duration_minutes"], 45)
        self.assertEqual(body["description"], "运行声音比平时更粗")

    def test_text_request_is_not_blocked_when_audio_is_disabled(self):
        with patch.dict(os.environ, {"GONGWEI_AUDIO_ENABLED": "false"}, clear=False):
            response = self.client.post("/api/inspection-requests", json={
                "pump_id": "pump-001", "work_date": self.date, "start_time": "09:00",
                "duration_minutes": 60, "description": "纯文字检查请求",
            })
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["status"], "draft")

    def test_create_complete_request_and_page_contract(self):
        response = self.client.post("/api/inspection-requests", json={
            "pump_id": "pump-001", "work_date": self.date, "start_time": "09:00",
            "duration_minutes": 60, "description": "页面合同测试",
        })
        self.assertEqual(response.status_code, 201)
        page = self.client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn("创建检查任务", page.text)
        self.assertIn("确认并创建工单", page.text)
        self.assertIn("模拟业务数据", page.text)
        self.assertIn("aria-live", page.text)
        self.assertIn("声音辅助（可选）", page.text)

    def test_confirm_recovers_when_work_order_response_is_lost_after_commit(self):
        from stage2_domain import create_plan, create_inspection_request, create_work_order_for_plan, reserve_plan_resources
        from stage2_aip import PartnerCallError

        request = create_inspection_request({
            "pump_id": "pump-001", "work_date": self.date, "start_time": "09:00",
            "duration_minutes": 60, "description": "响应丢失恢复测试",
        })
        plan = create_plan(request["id"])

        async def response_lost(kind, action, payload):
            if kind == "resource" and action == "reserve_resources":
                return {"result": {"reservations": reserve_plan_resources(payload["plan_id"])}}
            if kind == "workorder" and action == "create_work_order":
                create_work_order_for_plan(payload["plan_id"], payload["idempotency_key"])
                raise PartnerCallError("workorder", action, "响应在提交后丢失")
            raise AssertionError((kind, action))

        with patch.object(self.web_app, "call_partner", new=response_lost):
            response = self.client.post(f"/api/plans/{plan['id']}/confirm", headers={"Idempotency-Key": "lost-response"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["idempotent"])
        self.assertEqual(response.json()["work_order"]["status"], "confirmed")

    def test_agentic_conversation_exposes_multiturn_and_plan_contract(self):
        response = self.client.post("/api/conversations")
        self.assertEqual(response.status_code, 201)
        session_id = response.json()["session_id"]
        first = self.client.post(f"/api/conversations/{session_id}/messages", json={"text": "水泵001运行异常，帮我安排明天下午检查。"})
        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json()["status"], "awaiting_input")
        async def fake_call(kind, action, payload, **kwargs):
            return {"ok": True, "result": {"available": True, "request_id": payload["request_id"], "workers": [{"id": "worker-01", "name": "模拟人员甲"}], "inventory": [{"id": "tool-inspection-kit", "name": "便携检查工具包"}, {"id": "part-seal-ring", "name": "机械密封圈"}]}}
        with patch.object(self.web_app, "call_partner", new=fake_call):
            second = self.client.post(f"/api/conversations/{session_id}/messages", json={"text": "一小时，需要泵体检查技能。"})
        self.assertEqual(second.status_code, 200)
        body = second.json()
        self.assertEqual(body["status"], "ready_for_plan")
        self.assertTrue(body["plan"]["id"])
        self.assertEqual(body["task_id"], first.json()["task_id"])

    def test_browser_time_revision_refreshes_resources_and_keeps_main_task(self):
        from stage2_db import transaction
        from stage2_business_actions import dispatch_business_action
        client = TestClient(self.web_app.app, raise_server_exceptions=False)
        created = client.post("/api/conversations").json()
        original = "水泵001运行异常，帮我安排明天下午检查。"
        first = client.post(f"/api/conversations/{created['session_id']}/messages", json={"text": original, "message_id": "first"})
        self.assertEqual(first.status_code, 200)
        with transaction() as db:
            db.execute("UPDATE worker_availability SET end_time='15:00' WHERE worker_id='worker-01'")
        snapshots, query_ids = {}, []
        async def sdk_cached_call(kind, action, payload, **kwargs):
            task_id = kwargs["task_id"]
            query_ids.append(task_id)
            if task_id not in snapshots:
                snapshots[task_id] = dispatch_business_action(kind, action, payload)
            return snapshots[task_id]
        real_connect = sqlite3.connect
        def short_lock_timeout(*args, **kwargs):
            return real_connect(*args, **{**kwargs, "timeout": 0.1})
        with patch.object(self.web_app, "call_partner", new=sdk_cached_call), patch("stage2_db.sqlite3.connect", side_effect=short_lock_timeout):
            proposed = client.post(f"/api/conversations/{created['session_id']}/messages", json={"text": "下午两点开始，预计一小时，需要泵体检查技能。", "message_id": "supplement"})
            self.assertEqual(proposed.status_code, 200)
            revised = client.post(f"/api/conversations/{created['session_id']}/messages", json={"text": "刚才那个方案时间不合适，改到下午三点。", "message_id": "revision"})
        self.assertEqual(revised.status_code, 200, revised.text)
        before, after = proposed.json(), revised.json()
        self.assertEqual(after["task_id"], created["task_id"])
        self.assertEqual(after["plan"]["id"], before["plan"]["id"])
        self.assertEqual(after["plan"]["version"], before["plan"]["version"] + 1)
        self.assertEqual(after["request"]["plan"]["version"], after["plan"]["version"])
        self.assertEqual(after["request"]["start_time"], "15:00")
        self.assertEqual(after["request"]["description"], original)
        self.assertEqual(before["plan"]["worker_id"], "worker-01")
        self.assertEqual(after["plan"]["worker_id"], "worker-03")
        self.assertEqual(len(query_ids), 2)
        self.assertNotEqual(query_ids[0], query_ids[1])

    def test_agentic_task_cancel_and_status_endpoints_are_explicit(self):
        created = self.client.post("/api/conversations").json()
        cancelled = self.client.post(f"/api/tasks/{created['task_id']}/cancel", json={})
        self.assertEqual(cancelled.status_code, 200)
        self.assertEqual(cancelled.json()["status"], "cancelled")
        status = self.client.get("/api/platform/status")
        self.assertEqual(status.status_code, 200)
        self.assertFalse(status.json()["platform_verified"])
        agents = self.client.get("/api/agents/status")
        self.assertEqual(agents.status_code, 200)
        self.assertEqual(len(agents.json()), 3)

    def _agentic_plan(self):
        from agentic_core import create_conversation, handle_conversation_message
        from stage2_domain import create_plan
        created = create_conversation()
        message = handle_conversation_message(created["session_id"], "水泵001异常，2026-10-08上午9点检查，预计一小时")
        return created, create_plan(message["request"]["id"])

    @staticmethod
    async def _real_business_call(kind, action, payload, **kwargs):
        from stage2_business_actions import dispatch_business_action
        return dispatch_business_action(kind, action, payload)

    def test_cancelled_agent_task_cannot_be_confirmed(self):
        from stage2_db import connect_db
        created, plan = self._agentic_plan()
        self.client.post(f"/api/tasks/{created['task_id']}/cancel")
        with patch.object(self.web_app, "call_partner", new=self._real_business_call):
            response = self.client.post(f"/api/tasks/{created['task_id']}/confirm")
        self.assertEqual(response.status_code, 400)
        with connect_db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM work_orders").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reservations WHERE status='active'").fetchone()[0], 0)

    def test_task_cancel_cancels_created_work_order_and_releases_resources(self):
        from stage2_db import connect_db
        from stage2_domain import confirm_plan, get_work_order
        created, plan = self._agentic_plan()
        order = confirm_plan(plan["id"], "cancel-created-task")["work_order"]
        with patch.object(self.web_app, "call_partner", new=self._real_business_call):
            response = self.client.post(f"/api/tasks/{created['task_id']}/cancel")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(get_work_order(order["id"])["status"], "cancelled")
        with connect_db() as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM reservations WHERE status='active'").fetchone()[0], 0)

    def test_task_cancel_rejects_completed_work_order_without_changing_task(self):
        from stage2_db import transaction
        from stage2_domain import confirm_plan, update_work_order_status
        created, plan = self._agentic_plan()
        order = confirm_plan(plan["id"], "completed-task")["work_order"]
        update_work_order_status(order["id"], "completed")
        with transaction() as db:
            db.execute("UPDATE agent_tasks SET status='completed' WHERE task_id=?", (created["task_id"],))
        with patch.object(self.web_app, "call_partner", new=self._real_business_call):
            response = self.client.post(f"/api/tasks/{created['task_id']}/cancel")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.web_app._agent_task(created["task_id"])["status"], "completed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
