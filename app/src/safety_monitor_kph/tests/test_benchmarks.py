
"""
Latency micro-benchmarks for core reactions:
- AutoLockApp: Vehicle.Speed ↑ above threshold -> lock command publish
- SafetyApp: moving & door opens -> door alert publish
Notes:
* We measure "app reaction latency", not MQTT network latency.
* Each benchmark runs the scenario end-to-end in a fresh event loop per iteration.
"""

import os
import asyncio
from time import perf_counter

from safety_monitor_kph.tests.conftest import FakeVehicle, PublishCapture



def test_bench_autolock_lock_latency(benchmark, tmp_path, monkeypatch):
    """Speed rises above 5 kph -> AutoLock publishes 'vehicle/lockDoors' quickly."""
    # Make AutoLock deterministic for the run
    monkeypatch.setenv("AUTOLOCK_ENABLED", "true")
    from safety_monitor_kph import autolock_vapp as mod
    mod.STATE_FILE = str(tmp_path / "autolock.json")
    AutoLockApp = mod.AutoLockApp

    topic_lock = os.getenv("MQTT_TOPIC_LOCK_CMD", "vehicle/lockDoors")

    def run_once():
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            cap = PublishCapture()
            v = FakeVehicle(initial_speed=0.0)
            app = AutoLockApp(v) # type: ignore
            app.publish_event = cap  # type: ignore

            loop.run_until_complete(app.on_start())

            t0 = perf_counter()
            loop.run_until_complete(v.Speed.set_value_and_fire(10.0))  # cross threshold
            t1 = perf_counter()

            # (optional) flush tasks
            loop.run_until_complete(asyncio.sleep(0))
            # sanity: ensure a lock command happened this iteration
            locks = [e for e in cap.events if e[0] == topic_lock]
            assert locks and locks[-1][1] == {"command": "lock"}
            return t1 - t0
        finally:
            loop.close()

    duration = benchmark(run_once)  # seconds
    # Assert a reasonable budget for app reaction (tune if your box is slower)
    assert duration < 0.20  # 200 ms budget


def test_bench_safety_door_alert_latency(benchmark):
    """Door opens while moving -> SafetyApp publishes door alert quickly."""
    from safety_monitor_kph.safety_vapp import SafetyApp  # type: ignore

    topic_door = "ext/safety/door"

    def run_once():
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            cap = PublishCapture()
            v = FakeVehicle(initial_speed=0.0)
            app = SafetyApp(v) # type: ignore
            app.publish_event = cap  # type: ignore

            loop.run_until_complete(app.on_start())
            # Make the app "know" it's moving
            loop.run_until_complete(v.Speed.set_value_and_fire(12.0))

            t0 = perf_counter()
            loop.run_until_complete(app._on_door_front_left("true"))
            t1 = perf_counter()

            loop.run_until_complete(asyncio.sleep(0))
            # sanity: last door event should be active w/ frontLeft
            last = cap.last(topic_door)
            assert last is not None
            _, payload = last
            assert payload["state"] == "active" and payload["open"] == ["frontLeft"]

            return t1 - t0
        finally:
            loop.close()

    duration = benchmark(run_once)
    assert duration < 0.10  # 100 ms budget
