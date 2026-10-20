"""Conversation state and deterministic maintenance-request understanding.

The parser is intentionally small and auditable.  It is the local fallback
when no OpenAI-compatible LLM endpoint is configured; it never claims to have
used a model.  Business execution remains in ``stage2_domain`` and the two
official ACPs Partners.
"""
from __future__ import annotations

import json
import re
import uuid
from datetime import date, timedelta
from pathlib import Path
from typing import Any

from stage2_db import connect_db, initialize_database, transaction
from stage2_domain import create_inspection_request, get_request, now_utc, update_inspection_request
from llm_provider import configured as llm_configured, parse as parse_with_llm

MAX_MESSAGE_LENGTH = 4000
ANOMALY_MARKERS = ("异常", "故障", "异响", "漏水", "漏油", "振动", "发热", "噪声", "渗漏", "过热")
_PUMP_RE = re.compile(r"(?:水泵|泵)\s*[-_#]?\s*(\d{1,4})|pump[-_ ]?(\d{1,4})", re.I)
_DATE_RE = re.compile(r"(20\d{2})[-年](\d{1,2})[-月](\d{1,2})日?")
_DURATION_RE = re.compile(r"(\d+)\s*(?:小时|时|h|小时钟)", re.I)
_MINUTE_RE = re.compile(r"(\d+)\s*(?:分钟|min)", re.I)


def _id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4()}"


def _date_from_text(text: str, today: date) -> str | None:
    match = _DATE_RE.search(text)
    if match:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()
    if "后天" in text:
        return (today + timedelta(days=2)).isoformat()
    if "明天" in text:
        return (today + timedelta(days=1)).isoformat()
    if "今天" in text:
        return today.isoformat()
    return None


def _duration(text: str) -> int | None:
    match = _DURATION_RE.search(text)
    if match:
        return int(match.group(1)) * 60
    match = _MINUTE_RE.search(text)
    if match:
        return int(match.group(1))
    chinese = {"一": 1, "两": 2, "二": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    match = re.search(r"([一二两三四五六七八九])\s*(?:小时|时)", text)
    return chinese[match.group(1)] * 60 if match else None


def _time(text: str) -> str | None:
    match = re.search(r"(?<!\d)(\d{1,2})[:：](\d{2})", text)
    if match:
        hour, minute = int(match.group(1)), int(match.group(2))
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return f"{hour:02d}:{minute:02d}"
    match = re.search(r"(上午|下午|早上|晚上)\s*(\d{1,2}|[一二两三四五六七八九十]{1,3})点", text)
    if match:
        token = match.group(2)
        digits = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
        if token.isdigit():
            hour = int(token)
        elif "十" in token:
            tens, ones = token.split("十", 1)
            hour = digits.get(tens, 1) * 10 + digits.get(ones, 0)
        else:
            hour = digits.get(token, -1)
        if not 0 <= hour <= 23:
            raise ValueError("开始时间无效。")
        if match.group(1) in {"下午", "晚上"} and hour < 12:
            hour += 12
        return f"{hour:02d}:00"
    return None


def parse_maintenance_request(text: str, *, today: date | None = None) -> dict[str, Any]:
    if not isinstance(text, str) or not text.strip():
        raise ValueError("消息不能为空。")
    if len(text) > MAX_MESSAGE_LENGTH:
        raise ValueError("消息长度不能超过 4000 个字符。")
    today = today or date.today()
    normalized = text.strip()
    # DingDang can forward a transcript containing its own time/duration
    # examples. Parse the labelled human turns independently so quoted
    # suggestions never become schedule facts. This does not adopt/revive an
    # old protocol task or grant confirmation from a quoted transcript.
    # The homepage omits the original-request label and dedicated-task
    # footer. Split at the last candidate block so earlier human answers
    # can be parsed recursively when DingDang forwards several rounds.
    forwarded = re.fullmatch(
        r"(?:用户原始需求：\s*)?(.+)\n\s*上一轮候选结果：(.*)",
        normalized, re.S,
    )
    if forwarded and "用户回答：" in forwarded.group(2):
        original = forwarded.group(1).strip()
        answer = forwarded.group(2).rsplit("用户回答：", 1)[1].strip()
        answer = re.split(
            r"(?:^|\n)\s*(?:该智能体的专属补充任务|DAG 指定的上游产物摘要)：",
            answer, maxsplit=1,
        )[0].strip()
        if original:
            base = parse_maintenance_request(original, today=today)
            if not answer:
                return base
            supplement = parse_maintenance_request(answer, today=today)
            fields = _merged_fields(base["fields"], supplement)
            missing = [key for key in ("pump_id", "work_date", "start_time", "duration_minutes", "description") if not fields.get(key)]
            return {**supplement, "fields": fields, "missing_fields": missing}
    if llm_configured():
        model_intent = parse_with_llm(normalized, today=today)
        if model_intent is not None:
            return {
                "intent": model_intent.intent,
                "fields": model_intent.fields,
                "missing_fields": model_intent.missing_fields,
                "parser_mode": "openai_compatible",
            }
    fields: dict[str, Any] = {}
    match = _PUMP_RE.search(normalized)
    if match:
        number = match.group(1) or match.group(2)
        fields["pump_id"] = f"pump-{int(number):03d}"
    work_date = _date_from_text(normalized, today)
    if work_date:
        fields["work_date"] = work_date
    start_time = _time(normalized)
    if start_time:
        fields["start_time"] = start_time
    elif any(word in normalized for word in ("下午", "上午", "早上", "晚上")):
        fields["requested_period"] = "afternoon" if "下午" in normalized else "morning"
    duration = _duration(normalized)
    if duration is not None:
        fields["duration_minutes"] = duration
    skill = None
    for marker in ("需要", "需"):
        match = re.search(marker + r"([^，。；,;]+?)(?:技能|能力)(?:[。；,，]|$)", normalized)
        if match:
            skill = match.group(1).strip()
            break
    if skill:
        fields["required_skill"] = skill
    if any(word in normalized for word in (*ANOMALY_MARKERS, "检查", "检修")):
        fields["description"] = normalized
    intent = "cancel_task" if "取消" in normalized else "revise_task" if any(x in normalized for x in ("改到", "修改", "换到")) else "schedule_inspection"
    missing = [key for key in ("pump_id", "work_date", "start_time", "duration_minutes", "description") if not fields.get(key)]
    return {"intent": intent, "fields": fields, "missing_fields": missing, "parser_mode": "deterministic_fallback"}


def create_conversation(*, db_path: str | Path | None = None, session_id: str | None = None, task_id: str | None = None,
                        protocol_owner: dict[str, str] | None = None, allow_create: bool = True) -> dict[str, Any]:
    initialize_database(db_path)
    session_id, task_id = session_id or _id("session"), task_id or _id("task")
    timestamp = now_utc()
    with transaction(db_path) as conn:
        existing = conn.execute("SELECT session_id FROM agent_tasks WHERE task_id=?", (task_id,)).fetchone()
        if existing is not None and existing["session_id"] != session_id:
            raise ValueError("任务不属于此会话。")
        if protocol_owner is not None:
            session = conn.execute("SELECT 1 FROM agent_sessions WHERE session_id=?", (session_id,)).fetchone()
            contexts = conn.execute("SELECT context_json FROM agent_tasks WHERE session_id=?", (session_id,)).fetchall()
            if session and (not contexts or any(json.loads(row["context_json"]).get("protocol_owner") != protocol_owner for row in contexts)):
                raise ValueError("会话属于其他调用者或入口，不能采用已有任务。")
        if existing is None and not allow_create:
            raise ValueError("任务不存在，只有 start 可以创建新任务。")
        conn.execute("INSERT OR IGNORE INTO agent_sessions(session_id,leader_aic,status,created_at,updated_at) VALUES(?,?,?,?,?)", (session_id, "stage2-gongwei-leader", "active", timestamp, timestamp))
        if existing is None:
            context = {"protocol_owner": protocol_owner} if protocol_owner is not None else {}
            conn.execute("INSERT INTO agent_tasks(task_id,session_id,external_task_id,status,context_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?)", (task_id, session_id, task_id, "awaiting_input", json.dumps(context), timestamp, timestamp))
    return {"session_id": session_id, "task_id": task_id, "status": "active", "created_at": timestamp}


def _task(conn, session_id: str, task_id: str | None = None) -> dict[str, Any]:
    if task_id is not None:
        row = conn.execute("SELECT * FROM agent_tasks WHERE session_id=? AND task_id=?", (session_id, task_id)).fetchone()
    else:
        row = conn.execute("SELECT * FROM agent_tasks WHERE session_id=? ORDER BY created_at DESC, rowid DESC LIMIT 1", (session_id,)).fetchone()
    if row is None:
        raise ValueError("会话不存在。")
    result = dict(row)
    result["context"] = json.loads(result.pop("context_json") or "{}")
    return result


def _merged_fields(previous: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    merged = dict(previous)
    incoming = dict(parsed["fields"])
    if merged.get("description") and incoming.get("description") and not any(word in str(incoming["description"]) for word in ANOMALY_MARKERS):
        # Time/skill supplements can contain “检查” without describing a new
        # fault. Preserve the reported anomaly until the user updates it.
        incoming.pop("description")
    if incoming.get("requested_period") and not incoming.get("start_time"):
        merged.pop("start_time", None)
    merged.update({key: value for key, value in incoming.items() if value not in (None, "")})
    # A period is a user constraint.  When the user supplies only the period,
    # use a documented deterministic anchor so scheduling can continue.
    if merged.get("requested_period") == "afternoon" and not merged.get("start_time") and merged.get("duration_minutes"):
        merged["start_time"] = "13:00"
    elif merged.get("requested_period") == "morning" and not merged.get("start_time") and merged.get("duration_minutes"):
        merged["start_time"] = "09:00"
    return merged


def handle_conversation_message(session_id: str, text: str, *, db_path: str | Path | None = None, today: date | None = None, message_id: str | None = None, task_id: str | None = None) -> dict[str, Any]:
    initialize_database(db_path)
    # A persisted message is a receipt, not a new turn. Return the current
    # snapshot without parsing relative dates again or applying old fields.
    if message_id is not None:
        with connect_db(db_path) as conn:
            previous = conn.execute("SELECT task_id,content FROM agent_messages WHERE message_id=?", (message_id,)).fetchone()
            task = _task(conn, session_id, task_id) if previous is not None else None
        if previous is not None:
            if previous["task_id"] != task["task_id"] or previous["content"] != text:
                raise ValueError("消息 ID 已用于其他内容或任务。")
            return _message_snapshot(task, message_id, db_path)
    parsed = parse_maintenance_request(text, today=today)
    should_create_request = False
    request_id = None
    with transaction(db_path) as conn:
        task = _task(conn, session_id, task_id)
        if task["status"] in {"completed", "cancelled"}:
            raise ValueError("任务已结束，请创建新任务。")
        task_id = task["task_id"]
        message_id = message_id or _id("message")
        previous_message = conn.execute("SELECT task_id,content,parsed_json FROM agent_messages WHERE message_id=?", (message_id,)).fetchone()
        if previous_message is not None:
            if previous_message["task_id"] != task_id or previous_message["content"] != text:
                raise ValueError("消息 ID 已用于其他内容或任务。")
        else:
            conn.execute("INSERT INTO agent_messages(message_id,session_id,task_id,role,content,parsed_json,created_at) VALUES(?,?,?,?,?,?,?)", (message_id, session_id, task["task_id"], "user", text, json.dumps(parsed, ensure_ascii=False), now_utc()))
            fields = _merged_fields(task["context"].get("fields", {}), parsed)
            missing = [key for key in ("pump_id", "work_date", "start_time", "duration_minutes", "description") if not fields.get(key)]
            request_id = task.get("request_id")
            status = "awaiting_input" if missing else "ready_for_plan"
            should_create_request = bool(not missing and not request_id)
            context = {**task["context"], "fields": fields, "missing_fields": missing, "parser_mode": parsed["parser_mode"], "requested_period": fields.get("requested_period")}
            conn.execute("UPDATE agent_tasks SET status=?,request_id=?,context_json=?,updated_at=? WHERE task_id=?", (status, request_id, json.dumps(context, ensure_ascii=False), now_utc(), task_id))
            conn.execute("UPDATE agent_sessions SET updated_at=? WHERE session_id=?", (now_utc(), session_id))
    if previous_message is not None:
        return _message_snapshot(task, message_id, db_path)
    if should_create_request:
        request = create_inspection_request(fields, db_path)
        request_id = request["id"]
        with transaction(db_path) as conn:
            conn.execute("UPDATE agent_tasks SET request_id=?,updated_at=? WHERE task_id=?", (request_id, now_utc(), task_id))
    elif request_id:
        request = update_inspection_request(request_id, fields, db_path)
    request = get_request(request_id, db_path) if request_id else None
    question = "请补充：" + "、".join({"pump_id": "水泵", "work_date": "检查日期", "start_time": "开始时间", "duration_minutes": "预计时长", "description": "异常描述"}[key] for key in missing) if missing else None
    return {"session_id": session_id, "task_id": task["task_id"], "message_id": message_id, "status": status, "missing_fields": missing, "question": question, "request": request, "fields": fields, "parser_mode": parsed["parser_mode"]}


def _message_snapshot(task: dict[str, Any], message_id: str, db_path: str | Path | None) -> dict[str, Any]:
    context = task["context"]
    missing = context.get("missing_fields", [])
    if task["status"] == "ready_for_plan" and not missing and not task.get("request_id"):
        # A crash may occur after the message/context commits but before the
        # domain request exists. Resume from current fields, never old input.
        request = create_inspection_request(context["fields"], db_path)
        task["request_id"] = request["id"]
        with transaction(db_path) as conn:
            conn.execute("UPDATE agent_tasks SET request_id=?,updated_at=? WHERE task_id=?", (request["id"], now_utc(), task["task_id"]))
    question = "请补充：" + "、".join({"pump_id": "水泵", "work_date": "检查日期", "start_time": "开始时间", "duration_minutes": "预计时长", "description": "异常描述"}[key] for key in missing) if missing else None
    return {"session_id": task["session_id"], "task_id": task["task_id"], "message_id": message_id,
            "status": task["status"], "missing_fields": missing, "question": question,
            "request": get_request(task["request_id"], db_path) if task.get("request_id") else None,
            "fields": context.get("fields", {}), "parser_mode": context.get("parser_mode", "deterministic_fallback"), "duplicate": True}


def get_conversation(session_id: str, *, db_path: str | Path | None = None) -> dict[str, Any]:
    initialize_database(db_path)
    with connect_db(db_path) as conn:
        session = conn.execute("SELECT * FROM agent_sessions WHERE session_id=?", (session_id,)).fetchone()
        if session is None:
            raise ValueError("会话不存在。")
        task = _task(conn, session_id)
        messages = [dict(row) for row in conn.execute("SELECT * FROM agent_messages WHERE session_id=? ORDER BY created_at", (session_id,)).fetchall()]
    return {"session": dict(session), "task": task, "messages": messages, "request": get_request(task["request_id"], db_path) if task.get("request_id") else None}
