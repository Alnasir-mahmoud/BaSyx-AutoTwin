
from __future__ import annotations

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

log = logging.getLogger("ConfigWatcher")

OnChange = Callable[[dict[str, object]], None]
"""Signature: ``on_change(snapshots)`` where ``snapshots`` maps *basename*
(or alias) to the parsed JSON content of the freshly-changed files.
Files that did not change in this cycle are not included."""

@dataclass
class WatcherStats:
    started_at: float = field(default_factory=time.time)
    reload_cycles: int = 0
    reloads_applied: int = 0
    parse_errors: int = 0
    callback_errors: int = 0
    last_change_at: float | None = None
    last_error: str | None = None
    lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def snapshot(self) -> dict[str, object]:
        with self.lock:
            return {
                "uptimeSeconds": round(time.time() - self.started_at, 1),
                "reloadCycles": self.reload_cycles,
                "reloadsApplied": self.reloads_applied,
                "parseErrors": self.parse_errors,
                "callbackErrors": self.callback_errors,
                "lastChangeAt": self.last_change_at,
                "lastError": self.last_error,
            }

class ConfigWatcher:

    def __init__(
        self,
        paths: dict[str, str | Path],
        on_change: OnChange,
        *,
        interval_s: float = 1.0,
        initial_load: bool = True,
    ) -> None:
        if not paths:
            raise ValueError("At least one path must be specified.")
        self._paths = {alias: Path(p) for alias, p in paths.items()}
        self._on_change = on_change
        self._interval_s = interval_s
        self._initial_load = initial_load
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._last_signatures: dict[str, tuple[int, float]] = {}
        self.stats = WatcherStats()

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        if self._initial_load:
            self._apply_changes(force_all=True)
        self._thread = threading.Thread(
            target=self._run, name="ConfigWatcher", daemon=True,
        )
        self._thread.start()

    def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=timeout)

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def poll_once(self) -> int:
        return self._apply_changes()

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self._apply_changes()
            except Exception as exc:
                log.exception("watcher loop error: %s", exc)
                with self.stats.lock:
                    self.stats.last_error = f"loop: {exc}"
            self._stop.wait(self._interval_s)

    def _signature(self, path: Path) -> tuple[int, float] | None:
        try:
            st = os.stat(path)
        except FileNotFoundError:
            return None
        return (st.st_size, st.st_mtime)

    def _apply_changes(self, force_all: bool = False) -> int:
        with self.stats.lock:
            self.stats.reload_cycles += 1

        changed: dict[str, object] = {}
        for alias, path in self._paths.items():
            sig = self._signature(path)
            prev = self._last_signatures.get(alias)
            if sig is None:
                if prev is not None:
                    self._last_signatures.pop(alias, None)
                continue
            if force_all or prev != sig:
                try:
                    with open(path, "r", encoding="utf-8") as f:
                        content = json.load(f)
                except Exception as exc:
                    with self.stats.lock:
                        self.stats.parse_errors += 1
                        self.stats.last_error = f"{alias}: {exc}"
                    log.warning(
                        "Parse error for %s (%s) — keeping previous "
                        "snapshot.", path, exc,
                    )
                    continue
                changed[alias] = content
                self._last_signatures[alias] = sig

        if not changed:
            return 0

        with self.stats.lock:
            self.stats.reloads_applied += len(changed)
            self.stats.last_change_at = time.time()

        try:
            self._on_change(changed)
        except Exception as exc:
            with self.stats.lock:
                self.stats.callback_errors += 1
                self.stats.last_error = f"callback: {exc}"
            log.exception("on_change callback failed: %s", exc)

        return len(changed)
