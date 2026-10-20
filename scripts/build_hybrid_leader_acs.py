"""Produce the existing Leader's proposed ACS; never creates/submits a record."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from acps_sdk.acs import AgentCapabilitySpec

ROOT = Path(__file__).resolve().parents[1]
CURRENT_APPROVED = ROOT / 'platform/approved_acs/leader.json'
DEFAULT_OUTPUT = ROOT / 'reports/acs_1_1_0_draft/leader.json'

PIPE_MAINTENANCE_SKILL = {
    'id': 'gongwei.leader.pipe-maintenance',
    'name': '水管与管道检修协调',
    'description': '处理水管、管道、供水和循环水系统的漏水、堵塞、压力异常、阀门及泵体检修问题；协调现场检查人员、工具、配件和检查工单。',
    'tags': ['leader', 'agentic', '水管', '管道', '供水', '检修', '设备运维'],
    'examples': [
        '我有一个水管检修问题，帮我安排检查',
        '管道漏水或压力异常，需要协调人员和工具检查',
        '供水或循环水泵异常，安排检修并创建检查工单',
    ],
    'version': '1.1.0',
}

def _enhance_leader_skills(skills):
    """Add the pipe-maintenance vocabulary without replacing existing skills."""
    enhanced = [dict(skill) for skill in skills]
    for skill in enhanced:
        skill.setdefault('version', '1.1.0')
    if not any(skill.get('id') == PIPE_MAINTENANCE_SKILL['id'] for skill in enhanced):
        enhanced.insert(1, dict(PIPE_MAINTENANCE_SKILL))
    return enhanced


def build(output: Path = DEFAULT_OUTPUT, *, approved_path: Path = CURRENT_APPROVED):
    current = json.loads(CURRENT_APPROVED.read_text(encoding='utf-8'))
    approved = json.loads(approved_path.read_text(encoding='utf-8'))
    if not current.get('aic') or approved.get('aic') != current['aic']:
        raise ValueError('ACS AIC 与当前已批准 Leader 不一致；拒绝使用历史身份。')
    if not approved.get('active') or approved.get('name') != current['name']:
        raise ValueError('必须使用当前真实已批准且 active 的 Leader ACS。')
    if output.resolve() in {CURRENT_APPROVED.resolve(), approved_path.resolve()}:
        raise ValueError('不能覆盖已批准 ACS 输入。')
    draft = dict(approved)
    # The registry keeps a name+version history even after a record is deleted.
    # The replacement therefore uses the next version while retaining the same
    # Leader name and endpoint.
    draft['version'] = '1.1.1'
    draft['lastModifiedTime'] = datetime.now(timezone.utc).isoformat()
    draft['description'] = ('工维联设备检查协调智能体，面向水泵、水管、管道、供水或循环水系统及阀门等设备的异常检查与检修协调。'
        '接受中文自然语言或 JSON 请求，多轮补充设备、日期、开始时间、时长与技能；在线发现并通过正式 MQ 调用资源协调 Partner，'
        '查询人员、时间、工具和库存后返回待确认方案。仅用户明确确认后预留资源并调用工单处理 Partner，'
        '创建唯一检查工单并返回编号、人员、物品、时间及状态。支持任务查询、补充、确认、取消、'
        '重复确认保护和服务重启恢复。声音检测为可选辅助，不推断具体零件损坏。')
    draft['skills'] = _enhance_leader_skills(draft.get('skills', []))
    draft['endPoints'] = [{'url': 'https://leader.yanyi.online/rpc', 'transport': 'JSONRPC', 'security': [{'mtls': []}]}]
    draft['certificate'] = {'altNames': {'dns': ['leader.yanyi.online']}}
    draft['defaultInputModes'] = ['text/plain', 'application/json']
    draft['defaultOutputModes'] = ['text/plain', 'application/json']
    # The registry schema requires messageQueue even for an HTTPS-only endpoint.
    # Keep the explicit empty declaration; do not claim an unsupported queue.
    draft['capabilities'] = {'streaming': False, 'notification': False, 'messageQueue': []}
    # Retain the model's original dict so certificate SAN fields are not lost
    # if the installed model predates optional schema fields.
    AgentCapabilitySpec.model_validate(draft)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(draft, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--approved-acs', type=Path, default=CURRENT_APPROVED)
    parser.add_argument('--output', type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    output = build(args.output, approved_path=args.approved_acs)
    print(f'Validated ACS proposal, current AIC, not submitted: {output}')


if __name__ == '__main__':
    main()
