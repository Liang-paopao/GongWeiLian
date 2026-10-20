"""Local official AMP records for validated, running platform services.

Callers must obtain the AIC from configure_platform_environment and start
only after their service is ready. A separate Forwarder handles transport;
writing this file never establishes platform liveness by itself.
"""
from __future__ import annotations

import asyncio
import hashlib
import inspect
import math
import os
import signal
from collections.abc import Awaitable, Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any

from acps_sdk.amp import HeartbeatEmitter

ROOT = Path(__file__).resolve().parent


def runtime_log_dir() -> Path:
    return Path(os.environ.get("GONGWEI_LOG_DIR") or ROOT / "logs")


def inbox_is_connected(client: Any) -> bool:
    """Use SDK's public connection and aio-pika's live transport event.

    is_closed alone stays false during robust reconnection. connected is
    cleared on connection loss; a missing connection never counts as ready.
    """
    connection = client.connection
    return bool(connection is not None and not connection.is_closed and connection.connected.is_set())


async def inbox_is_ready(client: Any, channel: Any) -> bool:
    """Require the actual Inbox channel and its consumer restoration.

    Obtain channel from SDK ensure_inbox_queue().channel after consuming has
    started. RobustChannel.ready() waits for queue/consumer restoration; the
    connection's connected event is set earlier and cannot prove that alone.
    """
    if channel is None or channel.is_closed or not inbox_is_connected(client):
        return False
    connection = client.connection
    await channel.ready()
    return client.connection is connection and inbox_is_connected(client) and not channel.is_closed


class AmpHeartbeat:
    def __init__(self, *, role: str, aic: str, is_ready: Callable[[], bool | Awaitable[bool]] | None = None):
        if role not in {"leader_rpc", "leader_inbox", "resource", "workorder"}:
            raise ValueError("AMP role is not a formal service role")
        if not isinstance(aic, str) or not aic.strip():
            raise ValueError("AMP requires a validated AIC")
        try:
            self.interval_seconds = float(os.environ.get("GONGWEI_AMP_HEARTBEAT_INTERVAL_SECONDS", "15"))
        except ValueError as exc:
            raise ValueError("AMP heartbeat interval must be finite and positive") from exc
        if not math.isfinite(self.interval_seconds) or self.interval_seconds <= 0:
            raise ValueError("AMP heartbeat interval must be finite and positive")
        directory = Path(os.environ.get("GONGWEI_AMP_LOG_DIR") or runtime_log_dir() / "amp")
        # Full identity digest avoids path characters and case-folding collisions
        # on Windows. The unchanged AIC is present in every official record.
        identity = hashlib.sha256(aic.encode("utf-8")).hexdigest()
        self.log_file = directory / f"amp_heartbeat_{role}_{identity}.jsonl"
        self._aic = aic
        self._is_ready = is_ready
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is None or self._task.done():
            # Construct at startup so SDK uptime measures this running lifetime.
            emitter = HeartbeatEmitter(self.log_file, aic=self._aic)
            self._task = asyncio.create_task(self._run(emitter), name="gongwei-amp-heartbeat")

    async def _run(self, emitter: HeartbeatEmitter) -> None:
        while True:
            ready = True if self._is_ready is None else self._is_ready()
            if inspect.isawaitable(ready):
                ready = await ready
            if ready:
                writing = asyncio.create_task(emitter.emit())
                try:
                    await asyncio.shield(writing)
                except asyncio.CancelledError:
                    # SDK emit writes in a thread: cancellation must drain that
                    # write before stop returns, or a late line can look alive.
                    await writing
                    raise
            await asyncio.sleep(self.interval_seconds)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                with suppress(asyncio.CancelledError):
                    await self._task
            finally:
                self._task = None


@contextmanager
def shutdown_signals(stop: asyncio.Event) -> Iterator[None]:
    """Register graceful SIGINT/SIGTERM handlers on Unix and Windows."""
    loop = asyncio.get_running_loop()
    installed = []
    try:
        for sig in (signal.SIGINT, signal.SIGTERM):
            previous = signal.getsignal(sig)
            try:
                loop.add_signal_handler(sig, stop.set)
                native = True
            except NotImplementedError:
                signal.signal(sig, lambda *_: loop.call_soon_threadsafe(stop.set))
                native = False
            installed.append((sig, previous, native))
        yield
    finally:
        for sig, previous, native in installed:
            if native:
                loop.remove_signal_handler(sig)
            signal.signal(sig, previous)
