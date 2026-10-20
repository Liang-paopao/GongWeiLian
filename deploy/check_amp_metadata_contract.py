"""Exercise real aiokafka 0.12 metadata serialization without network I/O.

Run alongside amp_heartbeat_forwarder.py in the isolated diagnostics venv.
Only the broker connection is replaced; the real client/metadata code is used.
"""
import asyncio
import json


async def main():
    from aiokafka import __version__
    from aiokafka.client import AIOKafkaClient, ConnectionGroup
    from aiokafka.protocol.metadata import MetadataResponse
    from amp_heartbeat_forwarder import _all_topics_metadata_only

    client = AIOKafkaClient(bootstrap_servers="localhost:1", api_version="2.0.0")
    requests = []

    class Connection:
        async def send(self, request):
            requests.append({"topics": request.topics, "api_version": request.API_VERSION})
            return MetadataResponse[1]([(1, "unused", 9092, None)], 1, [])

        def close(self, **_kwargs):
            future = asyncio.get_running_loop().create_future()
            future.set_result(None)
            return future

    connection = Connection()
    client._conns[("bootstrap", ConnectionGroup.DEFAULT)] = connection

    async def get_connection(_node_id):
        return connection

    client._get_conn = get_connection
    _all_topics_metadata_only(client)
    try:
        await client._metadata_update(client.cluster, {"amp.heartbeat"})
        await client._metadata_update(client.cluster, {"deleted-topic"})
        assert len(requests) == 2 and all(r["topics"] is None for r in requests)
        print(json.dumps({"aiokafka_version": __version__, "network_requests": 0,
                          "actual_MetadataRequests": requests, "result": "PASS"}, indent=2))
    finally:
        await client.close()


if __name__ == "__main__":
    asyncio.run(main())
