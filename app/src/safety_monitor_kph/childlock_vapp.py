# childlock_vapp.py

from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional
import json

class DoorPosition(Enum):
    FRONT_LEFT = auto()
    FRONT_RIGHT = auto()
    REAR_LEFT = auto()
    REAR_RIGHT = auto()


class UnlockSource(Enum):
    INSIDE = auto()
    OUTSIDE = auto()
    REMOTE = auto()   # e.g., key fob / app

_MQTT_CLIENT = None
_EVENT_TOPIC = "ext/safety/childLock/events"  # adjust to your naming


def set_child_mode_mqtt_client(client, topic: Optional[str] = None) -> None:
    """Call this from your main file after creating the MQTT client."""
    global _MQTT_CLIENT, _EVENT_TOPIC
    _MQTT_CLIENT = client
    if topic:
        _EVENT_TOPIC = topic


def publish_child_mode_event(payload: dict) -> None:
    """Publish child mode events to MQTT or print if no client is set."""
    global _MQTT_CLIENT, _EVENT_TOPIC
    if _MQTT_CLIENT is not None:
        _MQTT_CLIENT.publish(_EVENT_TOPIC, json.dumps(payload), qos=1)
    else:
        # Fallback for local/manual testing
        print("[CHILD_MODE_EVENT]", payload)

@dataclass
class ChildModeConfig:
    """
    Configuration for Child Mode behavior.

    normal_lock_threshold_kph:
        Auto-lock speed threshold in normal mode.
    child_lock_threshold_kph:
        Stricter auto-lock speed threshold when Child Mode is enabled.
    block_rear_inside_unlock:
        If True, rear doors cannot be unlocked from inside in Child Mode.
    """
    normal_lock_threshold_kph: float = 10.0
    child_lock_threshold_kph: float = 5.0
    block_rear_inside_unlock: bool = True


class ChildModeController:
    """
    Encapsulates Child Mode state and rules.

    Responsible for:
      - Tracking whether Child Mode is enabled.
      - Computing effective auto-lock threshold.
      - Deciding whether a given unlock request is allowed.
    """

    def __init__(self, cfg: Optional[ChildModeConfig] = None):
        self._cfg = cfg or ChildModeConfig()
        self._enabled: bool = False

    # --- public state -------------------------------------------------------

    @property
    def enabled(self) -> bool:
        return self._enabled

    def set_enabled(self, enabled: bool) -> None:
        """Toggle Child Mode ON/OFF."""
        if self._enabled == enabled:
            return
        self._enabled = enabled
        if enabled:
            self._on_activated()
        else:
            self._on_deactivated()

    # --- thresholds & decisions --------------------------------------------

    def get_lock_threshold_kph(self, base_threshold_kph: float) -> float:
        """
        Return the effective auto-lock threshold.

        If Child Mode is ON, we enforce the stricter child threshold.
        Otherwise we keep the base behavior.
        """
        if self._enabled:
            return self._cfg.child_lock_threshold_kph
        return base_threshold_kph or self._cfg.normal_lock_threshold_kph

    def is_unlock_allowed(self, door: DoorPosition, source: UnlockSource) -> bool:
        """
        Decide whether a door unlock request should be allowed.

        In Child Mode we block rear doors being opened from INSIDE
        (if configured). Everything else behaves as normal.
        """
        if not self._enabled:
            return True

        if (
            self._cfg.block_rear_inside_unlock
            and source == UnlockSource.INSIDE
            and door in (DoorPosition.REAR_LEFT, DoorPosition.REAR_RIGHT)
        ):
            self._on_blocked_rear_inside_unlock(door)
            return False

        return True

    # --- event hooks (forwarded to MQTT/logging) ---------------------------

    def _on_activated(self) -> None:
        payload = {
            "event": "child_mode_activated",
            "normal_lock_threshold_kph": self._cfg.normal_lock_threshold_kph,
            "child_lock_threshold_kph": self._cfg.child_lock_threshold_kph,
        }
        publish_child_mode_event(payload)

    def _on_deactivated(self) -> None:
        payload = {"event": "child_mode_deactivated"}
        publish_child_mode_event(payload)

    def _on_blocked_rear_inside_unlock(self, door: DoorPosition) -> None:
        payload = {
            "event": "child_mode_blocked_rear_inside_unlock",
            "door": door.name,
        }
        publish_child_mode_event(payload)

class ChildModeVApp:
    """
    Vehicle app wrapper for Child Mode feature.

    This object is what your *_vapp_main.py will instantiate.
    """

    def __init__(self, cfg: Optional[ChildModeConfig] = None):
        self._cfg = cfg or ChildModeConfig()
        self._controller = ChildModeController(self._cfg)

    # --- API called from main file -----------------------------------------

    def set_child_mode(self, enabled: bool) -> None:
        """
        Called when driver presses Child Mode ON/OFF button
        (via MQTT or HMI event).
        """
        self._controller.set_enabled(enabled)

    def handle_speed(self, speed_kph: float, base_lock_threshold_kph: float) -> float:
        """
        Called when a new speed value is available.

        Returns the effective lock threshold for your existing auto-lock logic.
        """
        eff_threshold = self._controller.get_lock_threshold_kph(base_lock_threshold_kph)
        return eff_threshold

    def handle_unlock_request(self, door: DoorPosition, source: UnlockSource) -> bool:
        """
        Called before executing a door unlock operation.

        Returns True if unlock is allowed, False if blocked.
        """
        return self._controller.is_unlock_allowed(door, source)
