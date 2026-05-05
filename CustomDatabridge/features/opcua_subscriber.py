
from __future__ import annotations

import asyncio
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

log = logging.getLogger("OpcUaSubscriber")

@dataclass
class OpcUaNodeSpec:
    node_id: str
    name: str | None = None

OnDataChange = Callable[[str, Any, float], None]
"""Signature: (node_id, value, source_timestamp_unix_seconds) -> None."""

@dataclass
class SubscriberStats:
    started_at: float = field(default_factory=time.time)
    connects: int = 0
    reconnects: int = 0
    notifications: int = 0
    errors: int = 0
    last_error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "uptimeSeconds": round(time.time() - self.started_at, 1),
            "connects": self.connects,
            "reconnects": self.reconnects,
            "notifications": self.notifications,
            "errors": self.errors,
            "lastError": self.last_error,
        }

class _Handler:

    def __init__(self, subscriber: OpcUaSubscriber) -> None:
        self._sub = subscriber

    def datachange_notification(self, node, val, data):  # noqa: D401
        try:
            node_id = node.nodeid.to_string()
            src_ts = None
            try:
                mi = data.monitored_item.Value
                if mi.SourceTimestamp is not None:
                    src_ts = mi.SourceTimestamp.timestamp()
                elif mi.ServerTimestamp is not None:
                    src_ts = mi.ServerTimestamp.timestamp()
            except Exception:
                pass
            if src_ts is None:
                src_ts = time.time()

            self._sub.stats.notifications += 1
            self._sub.on_data_change(node_id, val, src_ts)
        except Exception as exc:
            self._sub.stats.errors += 1
            self._sub.stats.last_error = str(exc)
            log.exception("Handler error: %s", exc)

class OpcUaSubscriber:

    def __init__(
        self,
        endpoint: str,
        nodes: list[OpcUaNodeSpec],
        on_data_change: OnDataChange,
        *,
        sampling_interval_ms: int = 500,
        publishing_interval_ms: int = 500,
        reconnect_delay_s: float = 5.0,
    ) -> None:
        if not nodes:
            raise ValueError("At least one node must be specified.")
        self.endpoint = endpoint
        self.nodes = nodes
        self.on_data_change = on_data_change
        self.sampling_interval_ms = sampling_interval_ms
        self.publishing_interval_ms = publishing_interval_ms
        self.reconnect_delay_s = reconnect_delay_s
        self.stats = SubscriberStats()

        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._thread_entry,
            name=f"OpcUaSub[{self.endpoint}]",
            daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def _thread_entry(self) -> None:
        try:
            asyncio.run(self._async_main())
        except Exception as exc:
            self.stats.errors += 1
            self.stats.last_error = f"thread: {exc}"
            log.exception("Subscriber thread died: %s", exc)

    async def _async_main(self) -> None:
        from asyncua import Client

        self._loop = asyncio.get_running_loop()
        while not self._stop_event.is_set():
            try:
                await self._connect_and_subscribe(Client)
            except Exception as exc:
                self.stats.errors += 1
                self.stats.last_error = str(exc)
                log.warning("OPC UA loop error: %s — reconnect in %.1fs",
                            exc, self.reconnect_delay_s)
                if self._stop_event.is_set():
                    break
                await asyncio.sleep(self.reconnect_delay_s)
                self.stats.reconnects += 1

    async def _connect_and_subscribe(self, ClientCls) -> None:
        async with ClientCls(url=self.endpoint) as client:
            self.stats.connects += 1
            log.info("OPC UA connected: %s", self.endpoint)

            handler = _Handler(self)
            sub = await client.create_subscription(
                self.publishing_interval_ms, handler,
            )
            resolved = []
            for spec in self.nodes:
                try:
                    node = client.get_node(spec.node_id)
                    await sub.subscribe_data_change(node)
                    resolved.append(spec.node_id)
                except Exception as exc:
                    self.stats.errors += 1
                    self.stats.last_error = (
                        f"subscribe {spec.node_id}: {exc}"
                    )
                    log.error("subscribe_data_change %s failed: %s",
                              spec.node_id, exc)

            log.info("Subscribed to %d/%d node(s)",
                     len(resolved), len(self.nodes))

            while not self._stop_event.is_set():
                await asyncio.sleep(0.5)

            try:
                await sub.delete()
            except Exception:
                pass
