# SPDX-License-Identifier: Apache-2.0
"""
Latency micro-benchmarks for ChildLock core reactions:

- Rear door inside unlock while Child Mode ON -> blocked event
- Speed above child-mode max -> speed_exceeded event
- Moving + unfastened seatbelt in Child Mode -> seatbelt alert event

Notes:
* We measure controller reaction latency, not MQTT/network latency.
* Each benchmark runs a fresh controller and capture.
"""

import json
from time import perf_counter

from safety_monitor_kph.childlock_vapp_main import (
    ChildLockController,
    CHILD_MODE_MAX_SPEED_KPH,
)
from safety_monitor_kph.tests.conftest import PublishCapture  # type: ignore


class FakeMQTT:
    """Minimal MQTT stub that feeds publishes into PublishCapture."""

    def __init__(self, cap: PublishCapture):
        self.cap = cap

    def publish(self, topic: str, payload: str, qos: int = 0):
        try:
            data = json.loads(payload)
        except Exception:
            data = payload
        self.cap.events.append((topic, data))


def test_bench_childlock_rear_inside_block_latency(benchmark):
    """
    Child Mode ON + rearLeft inside unlock -> blocked event quickly.
    """
    cap = PublishCapture()
    client = FakeMQTT(cap)
    ctrl = ChildLockController(client) # type: ignore
    ctrl.handle_childlock_set("on")  # enable Child Mode

    def run_once():
        cap.events.clear()
        t0 = perf_counter()
        ctrl.handle_unlock_request("ext/doors/rearLeft/unlock", "inside")
        t1 = perf_counter()

        # sanity: ensure blocked event was emitted
        blocked = [
            e for e in cap.events
            if isinstance(e[1], dict)
            and e[1].get("event") == "child_mode_blocked_rear_inside_unlock"
        ]
        assert blocked, "Expected a blocked rear-left inside unlock event"
        return t1 - t0

    duration = benchmark(run_once)
    # keep it very small; adjust if your environment is slower
    assert duration < 0.01  # 10 ms budget


def test_bench_childlock_speed_exceeded_latency(benchmark):
    """
    Child Mode ON + speed above CHILD_MODE_MAX_SPEED_KPH -> speed_exceeded event quickly.
    """
    cap = PublishCapture()
    client = FakeMQTT(cap)
    ctrl = ChildLockController(client) # type: ignore
    ctrl.handle_childlock_set("on")

    above = CHILD_MODE_MAX_SPEED_KPH + 10.0

    def run_once():
        cap.events.clear()
        payload = json.dumps({"speedKph": above})
        t0 = perf_counter()
        ctrl.handle_safety_speed(payload)
        t1 = perf_counter()

        exceeded = [
            e for e in cap.events
            if isinstance(e[1], dict)
            and e[1].get("event") == "child_mode_speed_exceeded"
        ]
        assert exceeded, "Expected child_mode_speed_exceeded event"
        return t1 - t0

    duration = benchmark(run_once)
    assert duration < 0.01  # 10 ms budget


def test_bench_childlock_seatbelt_alert_latency(benchmark):
    """
    Child Mode ON + moving + anyUnfastened -> unfastened_seatbelt event quickly.
    """
    cap = PublishCapture()
    client = FakeMQTT(cap)
    ctrl = ChildLockController(client) # type: ignore
    ctrl.handle_childlock_set("on")

    seatbelt_payload = {
        "moving": True,
        "speedKph": 25.0,
        "anyUnfastened": True,
        "unfastened": ["row1_pos1"],
    }

    def run_once():
        cap.events.clear()
        t0 = perf_counter()
        ctrl.handle_safety_seatbelt(json.dumps(seatbelt_payload))
        t1 = perf_counter()

        alerts = [
            e for e in cap.events
            if isinstance(e[1], dict)
            and e[1].get("event") == "child_mode_unfastened_seatbelt"
        ]
        assert alerts, "Expected child_mode_unfastened_seatbelt event"
        return t1 - t0

    duration = benchmark(run_once)
    assert duration < 0.01  # 10 ms budget
