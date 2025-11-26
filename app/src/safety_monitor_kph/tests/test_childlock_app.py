# SPDX-License-Identifier: Apache-2.0

import json

from safety_monitor_kph.childlock_vapp_main import CHILD_MODE_MAX_SPEED_KPH, ChildLockController
from safety_monitor_kph.tests.conftest import PublishCapture  # type: ignore


class FakeMQTT:
    """
    Minimal fake MQTT client that routes publish() calls into a
    PublishCapture instance, so we can reuse the same test utilities
    as Phase-1 / Phase-2 tests.
    """

    def __init__(self, cap: PublishCapture):
        self.cap = cap

    def publish(self, topic: str, payload: str, qos: int = 0):
        # Mirror PublishCapture.__call__ JSON parsing behavior
        try:
            data = json.loads(payload)
        except Exception:
            data = payload
        self.cap.events.append((topic, data))

def test_child_mode_activation_and_deactivation():
    cap = PublishCapture()
    client = FakeMQTT(cap)
    ctrl = ChildLockController(client) # type: ignore

    # Turn ON
    ctrl.handle_childlock_set("on")
    assert ctrl.child_mode_enabled is True

    last = cap.last()
    assert last is not None
    _, payload_on = last
    assert payload_on["event"] == "child_mode_activated"

    # Turn OFF
    ctrl.handle_childlock_set("off")
    assert ctrl.child_mode_enabled is False

    last = cap.last()
    assert last is not None
    _, payload_off = last
    assert payload_off["event"] == "child_mode_deactivated"

def test_rear_left_inside_unlock_blocked_when_child_mode_on():
    cap = PublishCapture()
    client = FakeMQTT(cap)
    ctrl = ChildLockController(client) # type: ignore

    ctrl.handle_childlock_set("on")  # enable child mode
    ctrl.handle_unlock_request("ext/doors/rearLeft/unlock", "inside")

    last = cap.last()
    assert last is not None
    _, payload = last
    assert payload["event"] == "child_mode_blocked_rear_inside_unlock"
    assert payload["door"] == "REARLEFT"

def test_rear_left_inside_unlock_allowed_when_child_mode_off():
    cap = PublishCapture()
    client = FakeMQTT(cap)
    ctrl = ChildLockController(client) # type: ignore

    ctrl.handle_childlock_set("off")  # child mode disabled
    ctrl.handle_unlock_request("ext/doors/rearLeft/unlock", "inside")

    # No blocked event should be emitted when child mode is OFF
    events = [e for e in cap.events if isinstance(e[1], dict) and e[1].get("event") == "child_mode_blocked_rear_inside_unlock"]
    assert events == []

def test_rear_right_inside_unlock_blocked_when_child_mode_on():
    cap = PublishCapture()
    client = FakeMQTT(cap)
    ctrl = ChildLockController(client) # type: ignore

    ctrl.handle_childlock_set("on")  # enable child mode
    ctrl.handle_unlock_request("ext/doors/rearRight/unlock", "inside")

    last = cap.last()
    assert last is not None
    _, payload = last
    assert payload["event"] == "child_mode_blocked_rear_inside_unlock"
    assert payload["door"] == "REARRIGHT"

def test_speed_below_child_mode_limit_emits_no_event():
    cap = PublishCapture()
    client = FakeMQTT(cap)
    ctrl = ChildLockController(client) # type: ignore

    ctrl.handle_childlock_set("on")

    # Speed just below limit
    below = CHILD_MODE_MAX_SPEED_KPH - 1.0
    ctrl.handle_safety_speed(json.dumps({"speedKph": below}))

    # No child_mode_speed_exceeded event expected
    events = [
        e for e in cap.events
        if isinstance(e[1], dict) and e[1].get("event") == "child_mode_speed_exceeded"
    ]
    assert events == []

def test_speed_above_child_mode_limit_publishes_event():
    cap = PublishCapture()
    client = FakeMQTT(cap)
    ctrl = ChildLockController(client) # type: ignore

    ctrl.handle_childlock_set("on")

    # Speed above limit
    above = CHILD_MODE_MAX_SPEED_KPH + 5.0
    ctrl.handle_safety_speed(json.dumps({"speedKph": above}))

    last = cap.last()
    assert last is not None
    _, payload = last
    assert payload["event"] == "child_mode_speed_exceeded"
    assert payload["speedKph"] == above
    assert payload["limitKph"] == CHILD_MODE_MAX_SPEED_KPH

def test_seatbelt_unfastened_while_moving_generates_alert():
    cap = PublishCapture()
    client = FakeMQTT(cap)
    ctrl = ChildLockController(client) # type: ignore

    ctrl.handle_childlock_set("on")

    payload = {
        "moving": True,
        "speedKph": 25.0,
        "anyUnfastened": True,
        "unfastened": ["row1_pos1"],
    }
    ctrl.handle_safety_seatbelt(json.dumps(payload))

    last = cap.last()
    assert last is not None
    _, event = last
    assert event["event"] == "child_mode_unfastened_seatbelt"
    assert event["speedKph"] == 25.0
    assert event["unfastened"] == ["row1_pos1"]


def test_seatbelt_unfastened_but_stationary_no_alert():
    cap = PublishCapture()
    client = FakeMQTT(cap)
    ctrl = ChildLockController(client) # type: ignore

    ctrl.handle_childlock_set("on")

    payload = {
        "moving": False,
        "speedKph": 0.0,
        "anyUnfastened": True,
        "unfastened": ["row1_pos1"],
    }
    ctrl.handle_safety_seatbelt(json.dumps(payload))

    # No child_mode_unfastened_seatbelt event expected
    events = [
        e for e in cap.events
        if isinstance(e[1], dict) and e[1].get("event") == "child_mode_unfastened_seatbelt"
    ]
    assert events == []


def test_seatbelts_fastened_while_moving_no_alert():
    cap = PublishCapture()
    client = FakeMQTT(cap)
    ctrl = ChildLockController(client) # type: ignore

    ctrl.handle_childlock_set("on")

    payload = {
        "moving": True,
        "speedKph": 20.0,
        "anyUnfastened": False,
        "unfastened": [],
    }
    ctrl.handle_safety_seatbelt(json.dumps(payload))

    # No child_mode_unfastened_seatbelt event expected
    events = [
        e for e in cap.events
        if isinstance(e[1], dict) and e[1].get("event") == "child_mode_unfastened_seatbelt"
    ]
    assert events == []
