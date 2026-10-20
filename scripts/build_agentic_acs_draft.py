"""Build local-only ACS drafts; never submits them to the registry."""
from __future__ import annotations
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "platform" / "approved_acs"
TARGET = ROOT / "reports" / "acs_1_1_0_draft"

LEADER_SKILLS = [
    ("gongwei.leader.handle-maintenance-request", "理解设备异常请求", "接收中文自然语言和结构化检查请求，缺失字段时询问用户。"),
    ("gongwei.leader.pipe-maintenance", "水管与管道检修协调", "处理水管、管道、供水和循环水系统的漏水、堵塞、压力异常、阀门及泵体检修问题；协调现场检查人员、工具、配件和检查工单。"),
    ("gongwei.leader.plan-collaboration", "规划检查协作", "生成资源查询、确认和工单协作计划。"),
    ("gongwei.leader.discover-and-delegate", "发现并委派 Partner", "按能力、安全和在线状态发现并选择 Partner。"),
    ("gongwei.leader.resume-multiturn-task", "恢复多轮任务", "使用同一 session、task 和 message 关联补充信息。"),
    ("gongwei.leader.track-and-summarize", "跟踪并汇总结果", "返回协作轨迹、资源证据和工单结果。"),
]

LEADER_SKILL_TAGS = {
    "gongwei.leader.pipe-maintenance": ["leader", "agentic", "水管", "管道", "供水", "检修", "设备运维"],
}

LEADER_SKILL_EXAMPLES = {
    "gongwei.leader.pipe-maintenance": [
        "我有一个水管检修问题，帮我安排检查",
        "管道漏水或压力异常，需要协调人员和工具检查",
        "供水或循环水泵异常，安排检修并创建检查工单",
    ],
}

def main() -> None:
    TARGET.mkdir(parents=True, exist_ok=True)
    for name in ("leader", "resource_partner", "work_order_partner"):
        data = json.loads((SOURCE / f"{name}.json").read_text(encoding="utf-8"))
        # The registry retains the deleted Leader's name/version combination.
        # Keep Partners unchanged and generate the replacement Leader as 1.1.1.
        data["version"] = "1.1.1" if name == "leader" else "1.1.0"
        if not data.get('aic') or not data.get('active'):
            raise ValueError(f'{name}: 必须使用当前已批准 ACS 的真实 AIC')
        data["lastModifiedTime"] = datetime.now(timezone.utc).isoformat()
        data["defaultInputModes"] = ["text/plain", "application/json"]
        if name == "leader":
            data["skills"] = []
            for sid, title, desc in LEADER_SKILLS:
                skill = {
                    "id": sid,
                    "name": title,
                    "description": desc,
                    "tags": LEADER_SKILL_TAGS.get(sid, ["leader", "agentic"]),
                    "version": "1.1.0",
                }
                if sid in LEADER_SKILL_EXAMPLES:
                    skill["examples"] = LEADER_SKILL_EXAMPLES[sid]
                data["skills"].append(skill)
            data["description"] = "工维联设备检查协调 Leader，面向水泵、水管、管道、供水或循环水系统及阀门等设备的异常检查与检修协调；支持中文自然语言、多轮补充、Partner 发现、人员工具与库存协调、人工确认、唯一工单跟踪和可恢复任务。声音检测是可选辅助，不推断具体零件损坏。"
        out = TARGET / f"{name}.json"
        out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (TARGET / "README.md").write_text("# ACS 替换注册草稿\n\nLeader 使用 1.1.1 以避开已删除 1.1.0 的名称/版本历史约束；两个 Partner 保持 1.1.0。由 platform/approved_acs 当前批准快照生成，保留真实 AIC 和端点。脚本只生成草稿，不提交注册、不覆盖批准快照。本次生成时间不代表平台审核时间。\n", encoding="utf-8")

if __name__ == "__main__":
    main()
