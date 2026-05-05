
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from CustomDatabridge.features import (  # noqa: E402
    OpcUaNodeSpec,
    OpcUaSubscriber,
)

def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")

    endpoint = "opc.tcp://localhost:4840/simulation/"
    nodes = [
        OpcUaNodeSpec(node_id="ns=2;i=1001", name="Joint1_Position"),
        OpcUaNodeSpec(node_id="ns=2;i=1003", name="Robot_Speed"),
        OpcUaNodeSpec(node_id="ns=2;i=1004", name="Conveyor_Speed"),
    ]
    received: list[tuple[str, object, float]] = []

    def on_change(node_id, value, ts):
        received.append((node_id, value, ts))
        print(f"[CHANGE] {node_id:<12} value={value} ts={ts:.3f}",
              flush=True)

    sub = OpcUaSubscriber(
        endpoint=endpoint, nodes=nodes, on_data_change=on_change,
        sampling_interval_ms=500, publishing_interval_ms=500,
    )
    sub.start()

    deadline = time.time() + 10.0
    while time.time() < deadline and len(received) < 5:
        time.sleep(0.5)

    sub.stop()

    print("\n--- Summary ---")
    print(f"Notifications received : {len(received)}")
    print(f"Stats                  : {sub.stats.as_dict()}")

    if not received:
        print("[FAIL] No notifications — is the simulator running "
              "and reachable on port 4840?")
        return 1
    print("[OK] subscription active, notifications delivered.")
    return 0

if __name__ == "__main__":
    sys.exit(main())
