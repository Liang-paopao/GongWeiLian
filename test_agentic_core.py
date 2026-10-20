import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from agentic_core import parse_maintenance_request, create_conversation, handle_conversation_message
from stage2_db import initialize_database


class AgenticCoreTests(unittest.TestCase):
    def test_homepage_forwarded_answer_excludes_question_examples(self):
        text = ('水泵002运行异常，帮我安排明天下午检查。\n\n上一轮候选结果：\n\n'
                '叮当请求补充：具体是几点（例如明天14:00）？预计多久（例如60分钟）？\n'
                '用户回答：下午三点开始，预计一小时，需要泵体检查技能。\n\n'
                'DAG 指定的上游产物摘要：\n叮当已完成协作规划并开始按 DAG 派发。')
        result = parse_maintenance_request(text, today=date(2026, 10, 7))
        self.assertEqual(result['fields']['start_time'], '15:00')
        self.assertEqual(result['fields']['duration_minutes'], 60)
        self.assertEqual(result['fields']['pump_id'], 'pump-002')
        self.assertEqual(result['fields']['work_date'], '2026-10-08')
        self.assertEqual(result['fields']['description'], '水泵002运行异常，帮我安排明天下午检查。')
        self.assertEqual(result['missing_fields'], [])

    def test_nested_homepage_supplements_preserve_prior_human_fields(self):
        text = ('水泵002运行异常，明天下午检查。\n\n上一轮候选结果：\n'
                '叮当请求补充：例如14:00，60分钟。\n'
                '用户回答：下午三点开始，预计一小时，需要泵体检查技能。\n\n'
                '上一轮候选结果：\n叮当请求补充：候选方案16:00，120分钟。\n'
                '用户回答：时间不变，时长改为90分钟。\n\n'
                'DAG 指定的上游产物摘要：\n派发。')
        result = parse_maintenance_request(text, today=date(2026, 10, 7))
        self.assertEqual(result['fields']['start_time'], '15:00')
        self.assertEqual(result['fields']['duration_minutes'], 90)
        self.assertEqual(result['fields']['required_skill'], '泵体检查')
        self.assertNotIn('候选', result['fields']['description'])

    def test_forwarded_question_without_answer_does_not_fill_examples(self):
        text = ('水泵002运行异常，明天下午检查。\n\n上一轮候选结果：\n'
                '叮当请求补充：例如14:00，60分钟。\n用户回答：\n\n'
                'DAG 指定的上游产物摘要：\n派发。')
        result = parse_maintenance_request(text, today=date(2026, 10, 7))
        self.assertIn('start_time', result['missing_fields'])
        self.assertIn('duration_minutes', result['missing_fields'])

    def test_forwarded_user_answer_overrides_quoted_assistant_examples(self):
        text = ('用户原始需求：\n水泵001运行异常，明天下午检查。\n\n上一轮候选结果：\n'
                '叮当请求补充：例如 14:00、15:30，30 分钟、60 分钟。\n'
                '用户回答：下午三点开始，预计一小时，需要泵体检查技能。\n\n'
                '该智能体的专属补充任务：\n水泵001运行异常，明天下午检查。\n\n'
                'DAG 指定的上游产物摘要：\n开始派发。')
        result = parse_maintenance_request(text, today=date(2026, 10, 7))
        self.assertEqual(result['fields']['duration_minutes'], 60)
        self.assertEqual(result['fields']['start_time'], '15:00')
        self.assertEqual(result['fields']['work_date'], '2026-10-08')
        self.assertNotIn('例如', result['fields']['description'])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.db = Path(self.temp.name) / "agentic.db"
        initialize_database(self.db)

    def tearDown(self):
        self.temp.cleanup()

    def test_chinese_request_extracts_pump_and_tomorrow_afternoon(self):
        result = parse_maintenance_request("水泵001运行异常，帮我安排明天下午检查。", today=date(2026, 10, 5))
        self.assertEqual(result["fields"]["pump_id"], "pump-001")
        self.assertEqual(result["fields"]["work_date"], (date(2026, 10, 5) + timedelta(days=1)).isoformat())
        self.assertIn("start_time", result["missing_fields"])
        self.assertIn("duration_minutes", result["missing_fields"])
        self.assertEqual(result["intent"], "schedule_inspection")

    def test_multiturn_completion_keeps_one_task_id(self):
        session = create_conversation(db_path=self.db)
        first = handle_conversation_message(session["session_id"], "水泵001运行异常，帮我安排明天下午检查。", db_path=self.db, today=date(2026, 10, 5))
        self.assertEqual(first["status"], "awaiting_input")
        second = handle_conversation_message(session["session_id"], "一小时，需要泵体检查技能。", db_path=self.db, today=date(2026, 10, 5))
        self.assertEqual(second["status"], "ready_for_plan")
        self.assertEqual(first["task_id"], second["task_id"])
        self.assertEqual(second["request"]["duration_minutes"], 60)
        self.assertEqual(second["request"]["required_skill"], "泵体检查")

    def test_schedule_supplement_preserves_original_anomaly_description(self):
        session = create_conversation(db_path=self.db)
        original = "水泵001运行异常，帮我安排明天下午检查。"
        handle_conversation_message(session["session_id"], original, db_path=self.db)
        supplemented = handle_conversation_message(session["session_id"], "下午两点开始，预计一小时，需要泵体检查技能。", db_path=self.db)
        self.assertEqual(supplemented["request"]["description"], original)
        revised = handle_conversation_message(session["session_id"], "刚才那个方案时间不合适，改到下午三点。", db_path=self.db)
        self.assertEqual(revised["request"]["description"], original)
        changed = handle_conversation_message(session["session_id"], "补充异常：水泵出现漏水。", db_path=self.db)
        self.assertEqual(changed["request"]["description"], "补充异常：水泵出现漏水。")

    def test_invalid_message_is_rejected(self):
        session = create_conversation(db_path=self.db)
        with self.assertRaises(ValueError):
            handle_conversation_message(session["session_id"], "x" * 5001, db_path=self.db)

    def test_old_message_replay_keeps_latest_persisted_schedule(self):
        from stage2_db import connect_db
        session = create_conversation(db_path=self.db)
        text = "水泵001异常，2026-10-08下午两点检查，预计一小时"
        handle_conversation_message(session["session_id"], text, db_path=self.db, message_id="original")
        revised = handle_conversation_message(session["session_id"], "改到下午三点", db_path=self.db, message_id="revision")
        with connect_db(self.db) as db:
            events_before = db.execute("SELECT COUNT(*) FROM task_events").fetchone()[0]
        replay = handle_conversation_message(session["session_id"], text, db_path=self.db, message_id="original")
        self.assertEqual(replay["request"]["start_time"], revised["request"]["start_time"])
        with connect_db(self.db) as db:
            self.assertEqual(db.execute("SELECT COUNT(*) FROM task_events").fetchone()[0], events_before)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM agent_messages").fetchone()[0], 2)

    def test_replay_recovers_request_creation_interrupted_after_message_commit(self):
        session = create_conversation(db_path=self.db)
        text = "水泵001异常，2026-10-08下午两点检查，预计一小时"
        with patch("agentic_core.create_inspection_request", side_effect=RuntimeError("process stopped")):
            with self.assertRaisesRegex(RuntimeError, "process stopped"):
                handle_conversation_message(session["session_id"], text, db_path=self.db, message_id="interrupted")
        recovered = handle_conversation_message(session["session_id"], text, db_path=self.db, message_id="interrupted")
        self.assertIsNotNone(recovered["request"])
        self.assertEqual(recovered["request"]["start_time"], "14:00")

    def test_duplicate_arriving_during_parse_does_not_reapply_old_fields(self):
        session = create_conversation(db_path=self.db)
        text = "水泵001异常，2026-10-08下午两点检查，预计一小时"
        def other_turn_commits_while_parsing(value, **kwargs):
            with patch("agentic_core.parse_maintenance_request", new=parse_maintenance_request):
                handle_conversation_message(session["session_id"], text, db_path=self.db, message_id="original")
                handle_conversation_message(session["session_id"], "改到下午三点", db_path=self.db, message_id="revision")
            return parse_maintenance_request(value, **kwargs)
        with patch("agentic_core.parse_maintenance_request", side_effect=other_turn_commits_while_parsing):
            replay = handle_conversation_message(session["session_id"], text, db_path=self.db, message_id="original")
        self.assertEqual(replay["request"]["start_time"], "15:00")


if __name__ == "__main__":
    unittest.main()
