"""Partner discovery boundary with explicit online and local-fallback modes."""
from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit

from acps_sdk.adp import DiscoveryRequest, DiscoveryResponse

from stage2_db import initialize_database, transaction
from stage2_domain import now_utc

ROOT = Path(__file__).resolve().parent
ACS_DIR = ROOT / "reports" / "platform_mq_acs"


class PartnerResolver:
    def __init__(self, *, db_path: str | Path | None = None, discovery_url: str | None = None, strict_online: bool = False):
        self.db_path = db_path
        self.discovery_url = discovery_url
        self.strict_online = strict_online
        self.discovery_policy = os.environ.get("GONGWEI_PARTNER_DISCOVERY_POLICY", "default_online")
        if self.discovery_policy not in {"default_online", "platform_catalog"}:
            raise ValueError("未知 Partner 发现策略。")
        initialize_database(db_path)

    def _static(self, kind: str) -> list[dict[str, Any]]:
        filename = {"resource": "resource_partner.json", "workorder": "work_order_partner.json"}.get(kind)
        if not filename:
            raise ValueError("未知 Partner 类型。")
        path = ACS_DIR / filename
        acs = json.loads(path.read_text(encoding="utf-8"))
        endpoint = (acs.get("endPoints") or [{}])[0]
        return [{"aic": acs.get("aic") or f"local-{kind}", "name": acs.get("name"), "active": acs.get("active") is True, "protocolVersion": acs.get("protocolVersion"), "skills": [item.get("id") for item in acs.get("skills", [])], "inputModes": acs.get("defaultInputModes", []), "outputModes": acs.get("defaultOutputModes", []), "transport": endpoint.get("transport"), "endpoint": endpoint.get("url"), "security": list(acs.get("securitySchemes", {})), "online": False, "acs": acs}]

    def _online(self, kind: str, skills: list[str]) -> list[dict[str, Any]]:
        if not self.discovery_url:
            raise RuntimeError("未配置 discovery_server。")
        # Exact capability IDs and approved AICs are structured filters, not
        # natural-language semantic queries (which may return unrelated agents).
        conditions = [{"field": "active", "op": "eq", "value": True}]
        conditions.extend({"field": "skills.id", "op": "eq", "value": skill} for skill in skills)
        expected_aic = self._expected_aic(kind)
        if self.discovery_policy == "platform_catalog" and not expected_aic:
            raise RuntimeError("平台目录模式必须绑定已配置的真实 Partner AIC。")
        if expected_aic:
            conditions.append({"field": "aic", "op": "eq", "value": expected_aic})
        query = DiscoveryRequest(type="filtered", filter={"logic": "and", "conditions": conditions}, limit=10)
        payload = json.loads(query.to_json())
        if self.discovery_policy == "platform_catalog":
            # Explicit Wutong extension; never a retry/fallback or a claim that
            # its separate default online index is healthy. MQ verifies reachability.
            payload["extFilter"] = {"conditions": [{"field": "alive", "op": "in", "value": ["online", "offline", "unknown"]}]}
        base = self.discovery_url.rstrip("/")
        # The official Wutong/acps-cli gateway exposes the ADP route below the
        # discovery gateway.  Do not use the SDK's generic ``/discover``
        # constant here: that path is not mounted by this platform gateway.
        official_path = "/acps-adp-v2/discover"
        endpoint = base if base.endswith(official_path) else base + official_path
        request = urllib.request.Request(endpoint, data=json.dumps(payload).encode("utf-8"), headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(request, timeout=8) as response:
            raw_body = response.read().decode("utf-8")
            body = DiscoveryResponse.from_json(raw_body)
        if not body.is_success() or not body.result:
            raise RuntimeError("发现服务返回错误。")
        # aliveMap is a Wutong extension omitted by the SDK's ADP model.
        # Read it from the same actual response instead of inferring liveness
        # from the query policy or the mere presence of an ACS.
        alive_map = json.loads(raw_body).get("result", {}).get("aliveMap", {})
        if not isinstance(alive_map, dict):
            alive_map = {}
        candidates = []
        for aic, acs, skill, _group in body.result.iter_agent_skills():
            if skill.skill_id not in skills or not isinstance(acs, dict):
                continue
            endpoint = next((item for item in acs.get("endPoints", []) if item.get("transport") == "AMQP"), {})
            alive_info = alive_map.get(aic)
            alive_info = alive_info if isinstance(alive_info, dict) else {}
            alive = alive_info.get("alive")
            candidates.append({"aic": aic, "name": acs.get("name"), "active": acs.get("active") is True, "protocolVersion": acs.get("protocolVersion"), "skills": [item.get("id") for item in acs.get("skills", [])], "inputModes": acs.get("defaultInputModes", []), "outputModes": acs.get("defaultOutputModes", []), "transport": endpoint.get("transport"), "endpoint": endpoint.get("url"), "security": list(acs.get("securitySchemes", {})), "online": alive is True, "liveness": "online" if alive is True else "offline" if alive is False else "unknown", "aliveLastSeenAt": alive_info.get("aliveLastSeenAt"), "acs": acs})
            if self.discovery_policy == "platform_catalog":
                candidates[-1]["discovery_policy"] = "platform_catalog"
        return candidates

    def _expected_aic(self, kind: str) -> str | None:
        if not self.strict_online:
            return None
        return os.environ.get(f"GONGWEI_MQ_{kind.upper()}_AIC") or os.environ.get(f"MQ_{kind.upper()}_AIC")

    @staticmethod
    def _valid(candidate: dict[str, Any], skills: list[str]) -> tuple[bool, str]:
        if candidate.get("active") is not True:
            return False, "inactive"
        if str(candidate.get("protocolVersion", "")) < "02.02":
            return False, "protocol_version"
        if not set(skills).issubset(set(candidate.get("skills") or [])):
            return False, "skill_mismatch"
        if str(candidate.get("transport", "")).upper() != "AMQP":
            return False, "transport_missing"
        if "mtls" not in {str(value).lower() for value in (candidate.get("security") or [])}:
            return False, "mtls_missing"
        if "application/json" not in candidate.get("inputModes", []):
            return False, "input_mode"
        if "application/json" not in candidate.get("outputModes", []):
            return False, "output_mode"
        if not str(candidate.get("endpoint", "")).startswith("amqps://"):
            return False, "amqps_endpoint"
        return True, "matched"

    def resolve(self, kind: str, skills: list[str], *, task_id: str | None = None) -> dict[str, Any]:
        started = time.perf_counter()
        source = "discovery_server" if self.discovery_url else "static_fallback"
        if self.discovery_url and self.discovery_policy == "platform_catalog":
            source = "discovery_catalog"
        http_status: int | None = None
        try:
            raw = self._online(kind, skills) if (self.discovery_url or self.strict_online) else self._static(kind)
        except urllib.error.HTTPError as exc:
            http_status = int(exc.code)
            duration = round((time.perf_counter() - started) * 1000, 2)
            error = f"在线发现 HTTP {http_status}：{exc.reason or '请求失败'}"
            self._record(task_id, {"kind": kind, "skills": skills, "error": error, "http_status": http_status}, [], "discovery_failed", duration)
            return {"source": "discovery_failed", "candidates": [], "selected": None, "filtered": [{"reason": "discovery_http_error", "http_status": http_status}], "error": error, "http_status": http_status}
        except Exception as exc:
            duration = round((time.perf_counter() - started) * 1000, 2)
            self._record(task_id, {"kind": kind, "skills": skills, "error": type(exc).__name__}, [], "discovery_failed", duration)
            return {"source": "discovery_failed", "candidates": [], "selected": None, "filtered": [{"reason": "discovery_unavailable"}], "error": "在线发现暂时不可用，未静默使用固定 Partner。", "http_status": http_status}
        filtered = []
        valid = []
        expected_aic = self._expected_aic(kind)
        for candidate in raw:
            ok, reason = self._valid(candidate, skills)
            if expected_aic and candidate.get("aic") != expected_aic:
                ok, reason = False, "configured_identity_mismatch"
            elif expected_aic and parse_qs(urlsplit(candidate.get("endpoint") or "").query).get("inbox") != [f"inbox_{expected_aic}"]:
                ok, reason = False, "inbox_identity_mismatch"
            if ok:
                valid.append(candidate)
            else:
                filtered.append({"aic": candidate.get("aic"), "reason": reason})
        selected = valid[0] if valid else None
        duration = round((time.perf_counter() - started) * 1000, 2)
        self._record(task_id, {"kind": kind, "skills": skills}, raw, source, duration, selected=selected)
        return {"source": source, "candidates": valid, "filtered": filtered, "selected": selected, "duration_ms": duration, "error": None if selected else "没有符合能力和安全要求的 Partner。", "http_status": http_status}

    def _record(self, task_id: str | None, query: dict[str, Any], candidates: list[dict[str, Any]], source: str, duration: float, *, selected: dict[str, Any] | None = None):
        snapshot_id = f"snapshot-{uuid.uuid4()}"
        with transaction(self.db_path) as conn:
            conn.execute("INSERT INTO partner_discovery_snapshots(snapshot_id,task_id,query_json,candidates_json,source,duration_ms,created_at) VALUES(?,?,?,?,?,?,?)", (snapshot_id, task_id, json.dumps(query, ensure_ascii=False), json.dumps(candidates, ensure_ascii=False), source, duration, now_utc()))
            if selected:
                conn.execute("INSERT INTO partner_selections(selection_id,snapshot_id,partner_aic,reason,created_at) VALUES(?,?,?,?,?)", (f"selection-{uuid.uuid4()}", snapshot_id, str(selected.get("aic")), "能力匹配、active、AMQP、mTLS", now_utc()))
