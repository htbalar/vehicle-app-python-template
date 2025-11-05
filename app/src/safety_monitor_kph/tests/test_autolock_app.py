# SPDX-License-Identifier: Apache-2.0
import json
import os
import pytest

from safety_monitor_kph.autolock_vapp import AutoLockApp
from safety_monitor_kph.tests.conftest import FakeVehicle, PublishCapture  # type: ignore


@pytest.mark.asyncio
async def test_lock_when_speed_above_threshold_and_doors_closed(tmp_path, monkeypatch, publish_capture):
    """Speed > 5 and all doors closed -> lock once."""
    # Make the module deterministic for this test
    monkeypatch.setenv("AUTOLOCK_ENABLED", "true")
    from safety_monitor_kph import autolock_vapp as mod
    mod.STATE_FILE = str(tmp_path / "autolock.json")
    AutoLockApp = mod.AutoLockApp

    vehicle = FakeVehicle(initial_speed=0.0)
    app = AutoLockApp(vehicle) # type: ignore
    app.publish_event = publish_capture  # type: ignore
    await app.on_start()

    # Cross threshold
    await vehicle.Speed.set_value_and_fire(10.0)

    topic_lock = os.getenv("MQTT_TOPIC_LOCK_CMD", "vehicle/lockDoors")
    lock_events = [e for e in publish_capture.events if e[0] == topic_lock]
    assert len(lock_events) == 1
    assert lock_events[-1][1] == {"command": "lock"}


@pytest.mark.asyncio
async def test_pending_lock_then_lock_on_doors_closed(tmp_path, monkeypatch, publish_capture):
    """If doors open at speed > 5, set pending; lock when doors close while still > 5."""
    monkeypatch.setenv("AUTOLOCK_ENABLED", "true")
    from safety_monitor_kph import autolock_vapp as mod
    mod.STATE_FILE = str(tmp_path / "autolock.json")
    AutoLockApp = mod.AutoLockApp

    vehicle = FakeVehicle(initial_speed=0.0)
    app = AutoLockApp(vehicle) # type: ignore
    app.publish_event = publish_capture  # type: ignore
    await app.on_start()

    # Doors open first (AL learns anyOpen=true)
    await app.on_door_status(json.dumps({
        "moving": False, "anyOpen": True, "open": ["frontLeft"], "thresholdKph": 5.0, "state": "active"
    }))

    # Speed rises -> should defer (no lock yet)
    await vehicle.Speed.set_value_and_fire(12.0)

    topic_lock = os.getenv("MQTT_TOPIC_LOCK_CMD", "vehicle/lockDoors")
    assert not [e for e in publish_capture.events if e[0] == topic_lock]

    # Close doors while still moving -> must lock
    await app.on_door_status(json.dumps({
        "moving": True, "anyOpen": False, "open": [], "thresholdKph": 5.0, "state": "cleared"
    }))
    locks = [e for e in publish_capture.events if e[0] == topic_lock]
    assert len(locks) == 1 and locks[-1][1] == {"command": "lock"}



@pytest.mark.asyncio
async def test_doors_open_while_already_moving_sets_pending_then_locks_when_closed(publish_capture):
    """If doors open while already moving (>5), pending_lock is set and a later close triggers lock."""
    vehicle = FakeVehicle(initial_speed=8.0)  # already > 5
    app = AutoLockApp(vehicle) # type: ignore
    app.publish_event = publish_capture  # type: ignore
    await app.on_start()

    # Doors open at speed -> set pending (no lock)
    await app.on_door_status(json.dumps({
        "moving": True, "anyOpen": True, "open": ["frontRight"], "thresholdKph": 5.0, "state": "active"
    }))
    topic_lock = os.getenv("MQTT_TOPIC_LOCK_CMD", "vehicle/lockDoors")
    assert not [e for e in publish_capture.events if e[0] == topic_lock]

    # Doors close at same speed -> lock
    await app.on_door_status(json.dumps({
        "moving": True, "anyOpen": False, "open": [], "thresholdKph": 5.0, "state": "cleared"
    }))
    locks = [e for e in publish_capture.events if e[0] == topic_lock]
    assert len(locks) == 1 and locks[-1][1] == {"command": "lock"}


@pytest.mark.asyncio
async def test_unlock_when_speed_drops_below_threshold(tmp_path, monkeypatch, publish_capture):
    """Hysteresis: after lock at >5, dropping below 3 should unlock."""
    monkeypatch.setenv("AUTOLOCK_ENABLED", "true")
    from safety_monitor_kph import autolock_vapp as mod
    mod.STATE_FILE = str(tmp_path / "autolock.json")
    AutoLockApp = mod.AutoLockApp

    vehicle = FakeVehicle(initial_speed=0.0)
    app = AutoLockApp(vehicle) # type: ignore
    app.publish_event = publish_capture  # type: ignore
    await app.on_start()

    # Lock first
    await vehicle.Speed.set_value_and_fire(10.0)
    # Then drop below unlock threshold -> unlock
    await vehicle.Speed.set_value_and_fire(0.0)

    topic_unlock = os.getenv("MQTT_TOPIC_UNLOCK_CMD", "vehicle/unlockDoors")
    unlocks = [e for e in publish_capture.events if e[0] == topic_unlock]
    assert len(unlocks) >= 1 and unlocks[-1][1] == {"command": "unlock"}



@pytest.mark.asyncio
async def test_disable_via_config_stops_actions(publish_capture):
    """When disabled at runtime, no further lock/unlock commands are published."""
    vehicle = FakeVehicle(initial_speed=0.0)
    app = AutoLockApp(vehicle) # type: ignore
    app.publish_event = publish_capture  # type: ignore
    await app.on_start()

    # Disable via config topic
    await app.on_cfg_set("false")

    # Raise speed -> should NOT lock
    await vehicle.Speed.set_value_and_fire(12.0)

    topic_lock = os.getenv("MQTT_TOPIC_LOCK_CMD", "vehicle/lockDoors")
    locks = [e for e in publish_capture.events if e[0] == topic_lock]
    assert len(locks) == 0

    # Re-enable -> now lock should occur on next >5
    await app.on_cfg_set("true")
    await vehicle.Speed.set_value_and_fire(12.0)
    locks = [e for e in publish_capture.events if e[0] == topic_lock]
    assert len(locks) == 1 and locks[-1][1] == {"command": "lock"}


@pytest.mark.asyncio
async def test_pending_clears_when_speed_drops(publish_capture):
    """If pending_lock is set but speed falls below 3, pending should clear and unlock is sent (if needed)."""
    vehicle = FakeVehicle(initial_speed=0.0)
    app = AutoLockApp(vehicle) # type: ignore
    app.publish_event = publish_capture  # type: ignore
    await app.on_start()

    # Doors open first; then speed >5 to set pending (no lock yet)
    await app.on_door_status(json.dumps({
        "moving": False, "anyOpen": True, "open": ["frontLeft"], "thresholdKph": 5.0, "state": "active"
    }))
    await vehicle.Speed.set_value_and_fire(12.0)

    # Now drop speed below unlock threshold -> pending cleared and unlock published if it had locked
    await vehicle.Speed.set_value_and_fire(0.0)

    # No lock expected; but we do expect an unlock command if state was locked;
    # since it wasn't locked yet, just ensure no stray lock happened and pending cleared path didn't break anything.
    topic_lock = os.getenv("MQTT_TOPIC_LOCK_CMD", "vehicle/lockDoors")
    topic_unlock = os.getenv("MQTT_TOPIC_UNLOCK_CMD", "vehicle/unlockDoors")
    locks = [e for e in publish_capture.events if e[0] == topic_lock]
    # Should still be zero locks
    assert len(locks) == 0
    # And dropping speed produces an unlock (it's fine if app publishes unlock to enforce state)
    unlocks = [e for e in publish_capture.events if e[0] == topic_unlock]
    assert len(unlocks) >= 1 and unlocks[-1][1] == {"command": "unlock"}
    
@pytest.mark.asyncio
async def test_autolock_config_persists_across_restarts(tmp_path, monkeypatch):
    """on_cfg_set persists to file; new app instance restores same enabled value."""
    # Use a temp state file and ensure enabled default is True when file doesn't exist
    state_file = tmp_path / "autolock.json"
    monkeypatch.setenv("AUTOLOCK_ENABLED", "true")

    # Import module and override its STATE_FILE before constructing the app
    from safety_monitor_kph import autolock_vapp as mod
    mod.STATE_FILE = str(state_file)  # override module-level constant
    AutoLockApp = mod.AutoLockApp

    # First instance: disable via config and verify it writes the file
    v1 = FakeVehicle()
    app1 = AutoLockApp(v1) # type: ignore
    cap1 = PublishCapture()
    app1.publish_event = cap1  # type: ignore
    await app1.on_start()
    await app1.on_cfg_set("false")
    assert state_file.exists(), "state file should be created"

    # Second instance, same module/STATE_FILE → should load enabled=False
    v2 = FakeVehicle()
    app2 = AutoLockApp(v2) # type: ignore
    cap2 = PublishCapture()
    app2.publish_event = cap2  # type: ignore
    await app2.on_start()
    assert app2.enabled is False

    # And it should publish its state on start with enabled=false
    topic_state = os.getenv("MQTT_TOPIC_AUTOLOCK_CFG_STATE", "ext/safety/config/autolock")
    t, payload = cap2.last(topic_state) # type: ignore
    assert payload == {"enabled": False}
    
@pytest.mark.asyncio
async def test_autolock_publishes_config_state_on_start(tmp_path, monkeypatch):
    """On startup, AutoLock publishes ext/safety/config/autolock with current enabled flag."""
    # Fresh temp state: make sure no file exists so env default applies
    state_file = tmp_path / "autolock.json"
    monkeypatch.setenv("AUTOLOCK_ENABLED", "true")

    from safety_monitor_kph import autolock_vapp as mod
    mod.STATE_FILE = str(state_file)
    AutoLockApp = mod.AutoLockApp

    v = FakeVehicle()
    app = AutoLockApp(v) # type: ignore
    cap = PublishCapture()
    app.publish_event = cap  # type: ignore
    await app.on_start()

    topic_state = os.getenv("MQTT_TOPIC_AUTOLOCK_CFG_STATE", "ext/safety/config/autolock")
    last = cap.last(topic_state)
    assert last is not None
    _, payload = last
    assert payload == {"enabled": True}
    
@pytest.mark.asyncio
async def test_autolock_no_duplicate_lock_unlock_spam(tmp_path, monkeypatch):
    """Multiple speed events in same range should not produce duplicate lock/unlock."""
    # Ensure app starts enabled and uses a temp state file with no previous content
    state_file = tmp_path / "autolock.json"
    monkeypatch.setenv("AUTOLOCK_ENABLED", "true")

    from safety_monitor_kph import autolock_vapp as mod
    mod.STATE_FILE = str(state_file)
    AutoLockApp = mod.AutoLockApp

    v = FakeVehicle()
    app = AutoLockApp(v) # type: ignore
    cap = PublishCapture()
    app.publish_event = cap  # type: ignore
    await app.on_start()

    topic_lock = os.getenv("MQTT_TOPIC_LOCK_CMD", "vehicle/lockDoors")
    topic_unlock = os.getenv("MQTT_TOPIC_UNLOCK_CMD", "vehicle/unlockDoors")

    # Rise above lock threshold several times -> only first causes lock
    for s in (6.0, 8.0, 10.0, 9.5):
        await v.Speed.set_value_and_fire(s)
    locks = [e for e in cap.events if e[0] == topic_lock]
    assert len(locks) == 1 and locks[-1][1] == {"command": "lock"}

    # Drop below unlock threshold several times -> only first causes unlock
    for s in (2.5, 1.0, 0.0, 2.9):
        await v.Speed.set_value_and_fire(s)
    unlocks = [e for e in cap.events if e[0] == topic_unlock]
    assert len(unlocks) == 1 and unlocks[-1][1] == {"command": "unlock"}
