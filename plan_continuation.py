"""Explicit plan references across AIP tasks, with durable scope and revision checks.

This is business continuation, not resurrection of a canceled protocol task.
Only the authenticated RPC dispatcher may supply the ownership check.
"""
from contextvars import ContextVar
from datetime import datetime, timezone, timedelta
import hashlib
import json
import re

from stage2_db import connect_db, transaction
from stage2_domain import DomainError, get_plan, now_utc

owns_protocol_task = ContextVar('owns_protocol_task', default=lambda task_id: False)
REFERENCE = r'GW-[0-9a-f]{32}'


def latest_human_text(text: str) -> str:
    """Accept the current answer only, never a question/example or prior turn."""
    text = text.strip()
    if '\n' in text and '上一轮候选结果：' in text and '用户回答：' in text:
        blocks = re.split(r'^上一轮候选结果：', text, flags=re.MULTILINE)
        if len(blocks) < 2:
            return text
        answers = []
        for block in blocks[1:]:
            markers = list(re.finditer(r'^用户回答：', block, re.MULTILINE))
            # Real homepage requests accumulate complete round blocks. A
            # quoted/nested answer in any single block is not an authorization.
            if len(markers) != 1 or not re.search(r'^叮当请求补充：', block[:markers[0].start()], re.MULTILINE):
                return text
            answers.append(block[markers[0].end():].strip())
        text = answers[-1]
    return re.split(r'(?:^|\n)\s*(?:该智能体的专属补充任务|DAG 指定的上游产物摘要)：', text, maxsplit=1)[0].strip()


def explicit_reference(text: str) -> str | None:
    match = re.fullmatch(rf'(?:请)?确认方案\s*({REFERENCE})\s*并(?:创建|生成)工单[。！!]?', latest_human_text(text))
    return match.group(1) if match else None


def plan_fingerprint(plan: dict) -> str:
    request = plan['request']
    value = {'id': plan['id'], 'worker_id': plan['worker_id'], 'inventory': plan['inventory_json'],
             'request': {key: request.get(key) for key in ('id', 'pump_id', 'work_date', 'start_time', 'duration_minutes', 'required_skill', 'description')}}
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def issue_reference(task_id: str, plan: dict) -> str:
    fingerprint = plan_fingerprint(plan)
    reference = 'GW-' + hashlib.sha256((task_id + fingerprint).encode()).hexdigest()[:32]
    with transaction() as db:
        context = json.loads(db.execute('SELECT context_json FROM agent_tasks WHERE task_id=?', (task_id,)).fetchone()[0])
        previous = context.get('confirmation_offer') or {}
        context['confirmation_offer'] = {'reference': reference, 'fingerprint': fingerprint, 'plan_id': plan['id'],
                                         'issued_at': previous.get('issued_at') if previous.get('reference') == reference else now_utc()}
        context.pop('confirmation_withdrawn', None)
        db.execute('UPDATE agent_tasks SET context_json=? WHERE task_id=?', (json.dumps(context, ensure_ascii=False), task_id))
    return reference


def _without_transport_footer(value: str) -> str:
    parts = re.split(r'(?:^|\n)\s*(?:该智能体的专属补充任务|DAG 指定的上游产物摘要)：', value, maxsplit=1)
    if len(parts) > 1 and parts[1].strip() != '叮当已完成协作规划并开始按 DAG 派发。':
        raise DomainError('确认消息附加内容存在歧义，请直接回复方案编号确认句。')
    return parts[0].strip()


def bound_current_answer(text: str, source_id: str) -> str:
    """Extract one appended answer only when its history is already persisted."""
    with connect_db() as db:
        previous = db.execute("SELECT content FROM agent_messages WHERE task_id=? AND role='user' ORDER BY created_at DESC LIMIT 1", (source_id,)).fetchone()
    prefix = _without_transport_footer(previous[0]) if previous else ''
    current = _without_transport_footer(text)
    if not prefix or not current.startswith(prefix + '\n'):
        raise DomainError('确认上下文与已保存方案不一致，请直接回复方案编号确认句。')
    added = current[len(prefix):].strip()
    blocks = re.split(r'^上一轮候选结果：', added, flags=re.MULTILINE)
    markers = list(re.finditer(r'^用户回答：', added, re.MULTILINE))
    if len(blocks) != 2 or blocks[0] or len(markers) != 1 or not re.search(r'^叮当请求补充：', added[:markers[0].start()], re.MULTILINE):
        raise DomainError('确认文本包含引用或多个回答，请直接回复方案编号确认句。')
    return added[markers[0].end():].strip()


def _validate_confirmation_history(text: str, source_id: str, reference: str) -> None:
    direct = rf'(?:请)?确认方案\s*{re.escape(reference)}\s*并(?:创建|生成)工单[。！!]?'
    # A direct current answer can carry the homepage's fixed routing footer.
    # Do not strip arbitrary appended user text or trust a quoted history.
    if re.fullmatch(direct, _without_transport_footer(text)):
        return
    if not re.fullmatch(direct, bound_current_answer(text, source_id)):
        raise DomainError('尚未收到当前用户明确的方案确认。')


def adopt_reference(command, reference: str, confirmation_text: str) -> dict:
    with connect_db() as db:
        candidates = db.execute('SELECT task_id,context_json FROM agent_tasks WHERE session_id=?', (command.sessionId,)).fetchall()
    matches = []
    for row in candidates:
        context = json.loads(row['context_json'])
        offer = context.get('confirmation_offer') or {}
        if offer.get('reference') == reference and owns_protocol_task.get()(row['task_id']):
            matches.append((row['task_id'], context, offer))
    if len(matches) != 1:
        raise DomainError('方案编号无效、已更新或不属于当前调用者和会话，请重新获取待确认方案。')
    source_id, source, offer = matches[0]
    _validate_confirmation_history(confirmation_text, source_id, reference)
    plan = get_plan(offer['plan_id'])
    if source.get('confirmation_withdrawn') or plan['status'] == 'cancelled' or (plan.get('work_order') or {}).get('status') == 'cancelled':
        raise DomainError('此方案或工单已由用户取消，请重新提出检查需求。')
    if plan_fingerprint(plan) != offer['fingerprint']:
        raise DomainError('方案内容已经变化，请确认最新方案编号。')
    if not plan.get('work_order') and datetime.fromisoformat(offer['issued_at']) < datetime.now(timezone.utc) - timedelta(hours=24):
        raise DomainError('方案确认已过期，请重新查询资源并生成方案。')
    with transaction() as db:
        current = db.execute('SELECT request_id,context_json FROM agent_tasks WHERE task_id=?', (command.taskId,)).fetchone()
        if current['request_id'] and current['request_id'] != plan['request_id']:
            raise DomainError('当前任务已有另一项检查请求，不能确认其他方案。')
        context = json.loads(current['context_json'])
        context['plan_continuation'] = {'source_task_id': source_id, 'plan_id': plan['id'], 'reference': reference,
                                        'session_id': command.sessionId, 'sender_id': command.senderId,
                                        'confirmation_message_id': command.id, 'confirmed_at': now_utc()}
        db.execute('UPDATE agent_tasks SET request_id=?,plan_id=?,context_json=?,updated_at=? WHERE task_id=?',
                   (plan['request_id'], plan['id'], json.dumps(context, ensure_ascii=False), now_utc(), command.taskId))
    return context['plan_continuation']


def withdraw_reference(task_id: str) -> None:
    with transaction() as db:
        context = json.loads(db.execute('SELECT context_json FROM agent_tasks WHERE task_id=?', (task_id,)).fetchone()[0])
        context['confirmation_withdrawn'] = True
        db.execute('UPDATE agent_tasks SET context_json=? WHERE task_id=?', (json.dumps(context), task_id))


def adopt_unreserved_cancellation(command, text: str) -> dict | None:
    """Bind one appended cancellation to an owned, still-unreserved proposal.

    Homepage cancel/start changes the protocol task. This never cancels an
    order or reservations belonging to another task.
    """
    cancellation = r'(?:请)?取消(?:(?:这个|当前|此|该)?(?:任务|方案|工单))?[。！!]?'
    if not re.fullmatch(cancellation, latest_human_text(text)) or latest_human_text(text) == text:
        return None
    with connect_db() as db:
        candidates = db.execute('SELECT task_id,context_json FROM agent_tasks WHERE session_id=? AND task_id<>?', (command.sessionId, command.taskId)).fetchall()
    matches = []
    for row in candidates:
        source = json.loads(row['context_json'])
        offer = source.get('confirmation_offer') or {}
        if not offer or source.get('confirmation_withdrawn') or not owns_protocol_task.get()(row['task_id']):
            continue
        try:
            if not re.fullmatch(cancellation, bound_current_answer(text, row['task_id'])):
                continue
            plan = get_plan(offer['plan_id'])
            if plan['status'] != 'proposed' or plan.get('work_order') or plan_fingerprint(plan) != offer['fingerprint']:
                continue
        except DomainError:
            continue
        with connect_db() as db:
            if db.execute("SELECT 1 FROM reservations WHERE plan_id=? AND status='active'", (plan['id'],)).fetchone():
                continue
        matches.append((row['task_id'], plan, offer))
    if len(matches) != 1:
        return None
    source_id, plan, offer = matches[0]
    reference = offer['reference']
    continuation = {'source_task_id': source_id, 'plan_id': plan['id'], 'reference': reference,
                    'session_id': command.sessionId, 'sender_id': command.senderId, 'message_id': command.id,
                    'command_type': command.command.value}
    with transaction() as db:
        current = db.execute('SELECT request_id,context_json FROM agent_tasks WHERE task_id=?', (command.taskId,)).fetchone()
        if current['request_id'] and current['request_id'] != plan['request_id']:
            return None
        live = db.execute('SELECT * FROM plans WHERE id=?', (plan['id'],)).fetchone()
        if not live or live['status'] != 'proposed' or live['work_order_id'] or db.execute("SELECT 1 FROM reservations WHERE plan_id=? AND status='active'", (plan['id'],)).fetchone():
            return None
        source = json.loads(db.execute('SELECT context_json FROM agent_tasks WHERE task_id=?', (source_id,)).fetchone()[0])
        live_plan = dict(live)
        live_plan['inventory_json'] = json.loads(live_plan['inventory_json'])
        live_plan['request'] = dict(db.execute('SELECT * FROM inspection_requests WHERE id=?', (live['request_id'],)).fetchone())
        if source.get('confirmation_withdrawn') or source.get('confirmation_offer') != offer or plan_fingerprint(live_plan) != offer['fingerprint']:
            return None
        try:
            if not re.fullmatch(cancellation, bound_current_answer(text, source_id)):
                return None
        except DomainError:
            return None
        # Commit the cancellation before another process can reserve this plan.
        db.execute("UPDATE plans SET status='cancelled',updated_at=? WHERE id=?", (now_utc(), plan['id']))
        db.execute("UPDATE inspection_requests SET status='cancelled',updated_at=? WHERE id=?", (now_utc(), plan['request_id']))
        context = json.loads(current['context_json'])
        context['cancellation_continuation'] = continuation
        db.execute('UPDATE agent_tasks SET request_id=?,plan_id=?,context_json=? WHERE task_id=?',
                   (plan['request_id'], plan['id'], json.dumps(context, ensure_ascii=False), command.taskId))
        source['confirmation_withdrawn'] = True
        db.execute('UPDATE agent_tasks SET context_json=? WHERE task_id=?', (json.dumps(source, ensure_ascii=False), source_id))
    return continuation
