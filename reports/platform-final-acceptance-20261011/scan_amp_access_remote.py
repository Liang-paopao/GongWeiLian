"""Read-only, sanitized AMP Access evidence collector for the current live window.

This file is intentionally limited to protocol metadata. It never writes to Kafka,
uses no consumer group, and omits request/response bodies, headers and credentials.
Run it through the server's existing read-only SSH path; do not run a producer.
"""
import asyncio
import json
from datetime import datetime, timezone

from aiokafka import AIOKafkaConsumer
from aiokafka.structs import TopicPartition


BROKER = "wt.ioa.pub:19092"
TOPIC = "amp.access"
START = datetime(2026, 10, 10, 18, 50, tzinfo=timezone.utc)
END = datetime(2026, 10, 10, 19, 6, tzinfo=timezone.utc)
LEADER_AIC = "1.2.156.3088.1.BUPT.JSQB3Y.GD6IGY.AWF688.0WV9"


def safe_record(value, message, timestamp):
    body = value.get("body") if isinstance(value.get("body"), dict) else {}
    caller = body.get("caller") if isinstance(body.get("caller"), dict) else {}
    callee = body.get("callee") if isinstance(body.get("callee"), dict) else {}
    request = body.get("request") if isinstance(body.get("request"), dict) else {}
    response = body.get("response") if isinstance(body.get("response"), dict) else {}
    return {
        "partition": message.partition,
        "offset": message.offset,
        "kafka_timestamp": timestamp.isoformat(),
        "aic": value.get("aic"),
        "log_type": value.get("log_type"),
        "correlation_id": value.get("correlation_id"),
        "timestamp": value.get("timestamp"),
        "caller": {k: caller.get(k) for k in ("aic", "serviceName") if k in caller},
        "callee": {k: callee.get(k) for k in ("aic", "serviceName") if k in callee},
        "method": request.get("method"),
        "status_code": response.get("statusCode"),
    }


async def main():
    consumer = AIOKafkaConsumer(
        bootstrap_servers=BROKER,
        security_protocol="PLAINTEXT",
        group_id=None,
        enable_auto_commit=False,
        auto_offset_reset="earliest",
    )
    await consumer.start()
    records = []
    try:
        partitions = consumer.partitions_for_topic(TOPIC) or set()
        tps = [TopicPartition(TOPIC, p) for p in sorted(partitions)]
        offsets = await consumer.offsets_for_times(
            {tp: int(START.timestamp() * 1000) for tp in tps}
        )
        consumer.assign(tps)
        for tp in tps:
            offset = offsets.get(tp)
            if offset is not None:
                consumer.seek(tp, offset.offset)
        deadline = asyncio.get_running_loop().time() + 18
        while asyncio.get_running_loop().time() < deadline:
            batches = await consumer.getmany(timeout_ms=1500, max_records=1000)
            any_batch = False
            for _tp, messages in batches.items():
                for message in messages:
                    any_batch = True
                    if message.timestamp is None:
                        continue
                    timestamp = datetime.fromtimestamp(message.timestamp / 1000, timezone.utc)
                    if not START <= timestamp <= END:
                        continue
                    try:
                        value = json.loads(message.value.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    if not isinstance(value, dict):
                        continue
                    body = value.get("body") if isinstance(value.get("body"), dict) else {}
                    callee = body.get("callee") if isinstance(body.get("callee"), dict) else {}
                    if callee.get("aic") == LEADER_AIC:
                        records.append(safe_record(value, message, timestamp))
            if not any_batch and records:
                break
    finally:
        try:
            await consumer.stop()
        except BaseException:
            pass
    print(json.dumps({
        "topic": TOPIC,
        "broker": BROKER,
        "window_start": START.isoformat(),
        "window_end": END.isoformat(),
        "leader_aic": LEADER_AIC,
        "records": records,
        "count": len(records),
        "read_only": {
            "group_id": None,
            "enable_auto_commit": False,
            "producer_used": False,
            "records_written_to_kafka": False,
        },
    }, ensure_ascii=False, sort_keys=True, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
