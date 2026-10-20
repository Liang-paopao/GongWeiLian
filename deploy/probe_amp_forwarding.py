"""Bounded official aiokafka smoke path using ONLY fresh real SDK heartbeats.

Run in the isolated amp-diagnostics venv on the server. Never creates a topic,
fabricates a heartbeat, forwards historical records, or reads credentials.
Reference: official monitor-server/scripts/smoke_heartbeat.py (SDK v2.2.0).
The published 19092 endpoint speaks PLAINTEXT; this is not an mTLS claim.
"""
import asyncio
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

IDENTITIES = {
    "leader": "1.2.156.3088.1.BUPT.JSQB3Y.GD6IGY.AWF688.0WV9",
    "resource-inbox": "1.2.156.3088.1.BUPT.JSQB3Y.E164E8.FWIZ4R.03IA",
    "workorder-inbox": "1.2.156.3088.1.BUPT.JSQB3Y.Q9QG7Q.14TNDP.0WSF",
}


async def main():
    from aiokafka import AIOKafkaProducer

    report = {"checked_at": datetime.now(timezone.utc).isoformat(),
              "source": "official SDK HeartbeatEmitter files of running services",
              "broker": "wt.ioa.pub:19092", "security_protocol": "PLAINTEXT",
              "bounded_seconds": 45, "topic": "amp.heartbeat", "receipts": [],
              "platform_verified": False}
    producer = AIOKafkaProducer(bootstrap_servers=report["broker"],
                               client_id="gongwei-amp-bounded-probe",
                               security_protocol="PLAINTEXT", request_timeout_ms=8000, acks="all")
    started_at = datetime.now(timezone.utc)
    seen = set()
    try:
        await asyncio.wait_for(producer.start(), 15)
        # An all-topics metadata read cannot auto-create a missing topic.
        metadata = await asyncio.wait_for(producer.client.fetch_all_metadata(), 12)
        report["brokers"] = [{"id": b.nodeId, "host": b.host, "port": b.port} for b in metadata.brokers()]
        if report["topic"] not in metadata.topics():
            raise RuntimeError("Required topic absent; no publish and no automatic topic creation")
        report["partitions"] = sorted(metadata.partitions_for_topic(report["topic"]))
        deadline = time.monotonic() + report["bounded_seconds"]
        while time.monotonic() < deadline:
            for role, aic in IDENTITIES.items():
                if subprocess.run(["systemctl", "is-active", "--quiet", "gongwei-" + role]).returncode:
                    continue
                for path in Path("/var/log/gongwei-" + role + "/amp").glob("amp_heartbeat_*.jsonl"):
                    with path.open("rb") as handle:
                        handle.seek(max(0, path.stat().st_size - 4096))
                        lines = handle.read().splitlines()
                    if not lines:
                        continue
                    record = json.loads(lines[-1])
                    timestamp = datetime.fromisoformat(record["timestamp"])
                    if timestamp < started_at or record["log_id"] in seen:
                        continue
                    if set(record) != {"schema_version", "log_id", "log_type", "timestamp", "aic", "body"}:
                        raise RuntimeError("Unexpected heartbeat fields; refusing transmission")
                    if record["aic"] != aic or record["log_type"] != "heartbeat" or set(record["body"]) != {"uptimeSeconds"}:
                        raise RuntimeError("Unexpected heartbeat identity/type/body")
                    if not 0 <= (datetime.now(timezone.utc) - timestamp).total_seconds() <= 25:
                        continue
                    receipt = await asyncio.wait_for(producer.send_and_wait(
                        report["topic"], json.dumps(record, separators=(",", ":")).encode(), key=aic.encode()), 15)
                    seen.add(record["log_id"])
                    report["receipts"].append({"role": role, "aic": aic, "log_id": record["log_id"],
                                               "timestamp": record["timestamp"], "partition": receipt.partition,
                                               "offset": receipt.offset, "broker_timestamp": receipt.timestamp})
            await asyncio.sleep(1)
    except Exception as exc:
        report["error"] = {"type": type(exc).__name__, "message": str(exc)}
    finally:
        await asyncio.wait_for(producer.stop(), 15)
    report["all_three_acknowledged"] = set(IDENTITIES) <= {r["role"] for r in report["receipts"]}
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
