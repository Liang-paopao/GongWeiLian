"""Read-only simulated staff lookup. This does NOT reserve staff or create work orders."""
from __future__ import annotations
import json
from pathlib import Path
from typing import Any

DATA_FILE = Path(__file__).resolve().parent / "data" / "resources.json"


def lookup_staff(query: dict[str, Any], data_file: Path = DATA_FILE) -> dict[str, Any]:
    if not isinstance(query, dict):
        raise ValueError("查询必须是一组字段。")
    if query.get("action") != "lookup_staff":
        raise ValueError("这个助手目前只支持查询人员，不支持派单或修改库存。")
    device = query.get("device_id")
    slot = query.get("slot")
    if not isinstance(device, str) or not isinstance(slot, str):
        raise ValueError("缺少有效的 device_id 或 slot。")
    try:
        data = json.loads(data_file.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise ValueError(f"无法读取模拟数据：{exc}") from exc
    if not isinstance(data, dict) or data.get("simulated") is not True:
        raise ValueError("只允许使用明确标为 simulated=true 的练习数据。")
    if device not in data.get("device_ids", []):
        raise ValueError("该设备不在本机练习数据中。")
    if slot not in data.get("slots", {}):
        raise ValueError("该时间段不在本机练习数据中。")
    staff = data.get("staff")
    if not isinstance(staff, list):
        raise ValueError("模拟人员数据格式不正确。")
    available = []
    for person in staff:
        if not isinstance(person, dict):
            raise ValueError("模拟人员条目格式不正确。")
        if "pump_inspection" in person.get("skills", []) and slot in person.get("available_slots", []):
            available.append({"id": person["id"], "name": person["name"]})
    return {
        "simulated": True,
        "device_id": device,
        "slot": slot,
        "slot_description": data["slots"][slot],
        "available_staff": available,
        "staff_reserved": False,
        "work_order_created": False,
        "message": "已查到可用人员，尚未安排任务。" if available else "该时间段没有合适人员，不能声称安排成功。",
    }
