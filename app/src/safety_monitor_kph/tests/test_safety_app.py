# SPDX-License-Identifier: Apache-2.0
import pytest

from safety_monitor_kph.safety_vapp import SafetyApp
from safety_monitor_kph.tests.conftest import FakeVehicle  # type: ignore

@pytest.mark.asyncio
async def test_door_alert_activates_when_moving_and_one_door_opens(publish_capture):
    """
    Given the vehicle is moving (> threshold),
    When a single door opens,
    Then SafetyApp publishes an 'active' door alert with that door in the list.
    """
    # Arrange
    vehicle = FakeVehicle(initial_speed=0.0)
    app = SafetyApp(vehicle) # type: ignore
    app.publish_event = publish_capture  # type: ignore
    await app.on_start()

    # Move above threshold (defaults to 5 kph in the app)
    await vehicle.Speed.set_value_and_fire(10.0)

    # Act: open front-left door
    await app._on_door_front_left("true")

    # Assert: last door message is 'active' with frontLeft listed
    topic, payload = publish_capture.last(app.topic_door)
    assert payload["moving"] is True
    assert payload["state"] == "active"
    assert payload["anyOpen"] is True
    assert payload["open"] == ["frontLeft"]
    
@pytest.mark.asyncio
async def test_door_alert_clears_when_door_closes(publish_capture):
    """
    Given the vehicle is moving (> threshold) and a door is open (alert active),
    When that door closes,
    Then SafetyApp publishes a 'cleared' door alert with open=[].
    """

    vehicle = FakeVehicle(initial_speed=0.0)
    app = SafetyApp(vehicle) # type: ignore
    app.publish_event = publish_capture  # type: ignore
    await app.on_start()

    # Move above threshold and open door to activate alert
    await vehicle.Speed.set_value_and_fire(10.0)
    await app._on_door_front_left("true")

    # Sanity: last message should be active
    _, active_payload = publish_capture.last(app.topic_door)
    assert active_payload["state"] == "active"
    assert active_payload["anyOpen"] is True
    assert active_payload["open"] == ["frontLeft"]

    await app._on_door_front_left("false")
    _, cleared_payload = publish_capture.last(app.topic_door)
    assert cleared_payload["state"] == "cleared"
    assert cleared_payload["anyOpen"] is False
    assert cleared_payload["open"] == []

    
@pytest.mark.asyncio
async def test_door_aggregate_updates_when_multiple_open(publish_capture):
    # Arrange
    vehicle = FakeVehicle(initial_speed=0.0)
    app = SafetyApp(vehicle) # type: ignore
    # Capture publishes
    app.publish_event = publish_capture  # type: ignore
    # Start app: subscribe speed
    await app.on_start()

    # Set speed above threshold to enable alerts
    await vehicle.Speed.set_value_and_fire(10.0)

    # Act: open FL then FR via MQTT handlers
    await app._on_door_front_left("true")
    await app._on_door_front_right("true")

    # Assert: Last door message should contain both FL and FR
    last = publish_capture.last(app.topic_door)
    assert last is not None
    _, payload = last
    assert payload["moving"] is True
    assert payload["anyOpen"] is True
    assert set(payload["open"]) == {"frontLeft", "frontRight"}

    # Close FR, keep FL open -> list should shrink
    await app._on_door_front_right("false")
    last = publish_capture.last(app.topic_door)
    assert set(last[1]["open"]) == {"frontLeft"}

    # Close FL -> cleared
    await app._on_door_front_left("false")
    last = publish_capture.last(app.topic_door)
    assert last[1]["state"] == "cleared"
    assert last[1]["anyOpen"] is False
    assert last[1]["open"] == []


@pytest.mark.asyncio
async def test_seatbelt_aggregate_updates_and_clears(publish_capture):
    vehicle = FakeVehicle(initial_speed=12.0)
    app = SafetyApp(vehicle) # type: ignore
    app.publish_event = publish_capture  # type: ignore
    await app.on_start()

    # Initially both belts are fastened (no publish until active)
    await vehicle.Speed.set_value_and_fire(12.0)

    # Unfasten pos1 -> should activate
    await app._on_belt_row1_pos1("false")
    last = publish_capture.last(app.topic_seatbelt)
    assert last is not None
    _, payload = last
    assert payload["state"] == "active"
    assert payload["anyUnfastened"] is True
    assert payload["unfastened"] == ["row1_pos1"]

    # Also unfasten pos2 -> still active but list should update
    await app._on_belt_row1_pos2("false")
    last = publish_capture.last(app.topic_seatbelt)
    assert set(last[1]["unfastened"]) == {"row1_pos1", "row1_pos2"}

    # Fasten both -> cleared
    await app._on_belt_row1_pos1("true")
    await app._on_belt_row1_pos2("true")
    last = publish_capture.last(app.topic_seatbelt)
    assert last[1]["state"] == "cleared"
    assert last[1]["anyUnfastened"] is False
    assert last[1]["unfastened"] == []

@pytest.mark.asyncio
async def test_no_door_alert_when_stationary(publish_capture):
    vehicle = FakeVehicle(initial_speed=0.0)
    app = SafetyApp(vehicle) # type: ignore
    app.publish_event = publish_capture  # type: ignore
    await app.on_start()

    # Below threshold: open door -> should NOT publish 'active'
    await app._on_door_front_left("true")

    # There should be no publish to the door topic yet
    last = publish_capture.last(app.topic_door)
    assert last is None

@pytest.mark.asyncio
async def test_door_alert_debounce_two_ticks(monkeypatch, publish_capture):
    # Require two consecutive evaluations to activate
    monkeypatch.setenv("SAFETY_DEBOUNCE_COUNT", "2")

    vehicle = FakeVehicle(initial_speed=0.0)
    app = SafetyApp(vehicle) # type: ignore
    app.publish_event = publish_capture  # type: ignore
    await app.on_start()

    # Move above threshold
    await vehicle.Speed.set_value_and_fire(10.0)

    # First tick with door open -> no 'active' yet (up=1)
    await app._on_door_front_left("true")
    assert publish_capture.last(app.topic_door) is None

    # Second tick (re-trigger evaluation). Re-fire same speed to tick.
    await vehicle.Speed.set_value_and_fire(10.0)

    # Now it should publish 'active'
    _, payload = publish_capture.last(app.topic_door)
    assert payload["state"] == "active"
    assert payload["anyOpen"] is True
    assert payload["open"] == ["frontLeft"]

@pytest.mark.asyncio
async def test_door_alert_clears_on_speed_drop(publish_capture):
    vehicle = FakeVehicle(initial_speed=0.0)
    app = SafetyApp(vehicle) # type: ignore
    app.publish_event = publish_capture  # type: ignore
    await app.on_start()

    # Moving + door open -> active
    await vehicle.Speed.set_value_and_fire(10.0)
    await app._on_door_front_left("true")
    _, p_active = publish_capture.last(app.topic_door)
    assert p_active["state"] == "active"

    # Drop speed below threshold -> should clear even if door still open
    await vehicle.Speed.set_value_and_fire(0.0)
    _, p_clear = publish_capture.last(app.topic_door)
    assert p_clear["state"] == "cleared"
    assert p_clear["moving"] is False

@pytest.mark.asyncio
async def test_seatbelt_republishes_when_list_changes_while_active(publish_capture):
    """With active alert, changing the set of unfastened belts republishes updated content."""

    vehicle = FakeVehicle(initial_speed=12.0)
    app = SafetyApp(vehicle) # type: ignore
    app.publish_event = publish_capture  # type: ignore
    await app.on_start()

    # NEW: send a speed callback so the app knows it's moving
    await vehicle.Speed.set_value_and_fire(12.0)  # <-- important
    # (now moving=True inside the app)

    # Activate with one unfastened belt
    await app._on_belt_row1_pos1("false")
    _, p1 = publish_capture.last(app.topic_seatbelt)
    assert p1["state"] == "active"
    assert p1["unfastened"] == ["row1_pos1"]

    # Change content: unfasten another belt (still active)
    await app._on_belt_row1_pos2("false")
    _, p2 = publish_capture.last(app.topic_seatbelt)
    assert p2["state"] == "active"
    assert set(p2["unfastened"]) == {"row1_pos1", "row1_pos2"}

    # Ensure there were at least 2 seatbelt publishes (initial active + update)
    seatbelt_events = [e for e in publish_capture.events if e[0] == app.topic_seatbelt]
    assert len(seatbelt_events) >= 2
