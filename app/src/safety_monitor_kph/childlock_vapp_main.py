import json
import logging
import os
from typing import Any, Dict

import paho.mqtt.client as mqtt  # type: ignore

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("childlock_vapp")

# -------- Config / Topics --------

BROKER_HOST = os.getenv("MQTT_BROKER_HOST", "127.0.0.1")
BROKER_PORT = int(os.getenv("MQTT_BROKER_PORT", "1883"))

# Child mode control + events
TOPIC_CHILDLOCK_SET = os.getenv("MQTT_TOPIC_CHILDLOCK_SET", "vehicle/childLock/set")
TOPIC_CHILDLOCK_EVENTS = os.getenv(
    "MQTT_TOPIC_CHILDLOCK_EVENTS", "ext/safety/childLock/events"
)

# Reuse existing safety + autolock topics
TOPIC_SAFETY_DOOR = os.getenv("TOPIC_DOOR", "ext/safety/door")
TOPIC_SAFETY_SEATBELT = os.getenv("TOPIC_SEATBELT", "ext/safety/seatbelt")
TOPIC_SAFETY_SPEED = os.getenv("TOPIC_SPEED", "ext/safety/speed")
TOPIC_AUTOLOCK_CFG_SET = os.getenv(
    "MQTT_TOPIC_AUTOLOCK_CFG_SET", "safety/config/autolock/set"
)

# Door unlock requests (same pattern you already used)
# e.g., ext/doors/rearLeft/unlock with payload "inside" or "outside"
DOOR_UNLOCK_PATTERN = "ext/doors/+/unlock"

# Child mode specific limits (can be tuned via env later)
CHILD_MODE_MAX_SPEED_KPH = float(os.getenv("CHILD_MODE_MAX_SPEED_KPH", "30.0"))


class ChildLockController:
    """
    Child Mode controller:
      - Toggles child mode via vehicle/childLock/set.
      - Blocks rear door unlocks from INSIDE when child mode is ON.
      - Listens to SafetyApp aggregates (ext/safety/door + ext/safety/seatbelt)
        and emits extra childLock events when:
          * speed exceeds CHILD_MODE_MAX_SPEED_KPH
          * any seatbelt is unfastened while moving
      - Forces AutoLock enabled when child mode is turned ON.
    """

    def __init__(self, client: mqtt.Client) -> None:
        self.client = client
        self.child_mode_enabled: bool = False

        # Snapshot of latest safety state
        self.last_speed_kph: float = 0.0
        self.moving: bool = False
        self.any_door_open: bool = False
        self.any_unfastened: bool = False

    # ------- helpers -------

    def _publish_event(self, event: Dict[str, Any]) -> None:
        payload = json.dumps(event)
        logger.info("[EVENT] %s", payload)
        self.client.publish(TOPIC_CHILDLOCK_EVENTS, payload, qos=1)

    def _set_child_mode(self, enabled: bool) -> None:
        if enabled == self.child_mode_enabled:
            # No change
            return

        self.child_mode_enabled = enabled
        logger.info("Child Mode set to: %s", enabled)

        if enabled:
            print("Child Mode set to: True")
            # Force AutoLock ON (do not force it OFF when child mode disables)
            self.client.publish(TOPIC_AUTOLOCK_CFG_SET, "true", qos=1)
            self._publish_event(
                {
                    "event": "child_mode_activated",
                    "normal_lock_threshold_kph": float(
                        os.getenv("AUTOLOCK_LOCK_ABOVE_KPH", "5.0")
                    ),
                    "child_lock_threshold_kph": CHILD_MODE_MAX_SPEED_KPH,
                }
            )
        else:
            print("Child Mode set to: False")
            self._publish_event({"event": "child_mode_deactivated"})

    # ------- handlers for MQTT messages -------

    def handle_childlock_set(self, payload: str) -> None:
        raw = payload.strip().lower()
        logger.info("[MQTT] %s -> %s", TOPIC_CHILDLOCK_SET, raw)

        enabled = raw in ("on", "1", "true", "yes")
        self._set_child_mode(enabled)

    def handle_unlock_request(self, topic: str, payload: str) -> None:
        parts = topic.split("/")
        if len(parts) < 4:
            return

        door_id = parts[2]  # ext / doors / <door> / unlock
        source = payload.strip().lower()

        logger.info("[MQTT] %s -> %s", topic, source)

        # Only block rear doors from INSIDE when child mode is ON
        if (
            self.child_mode_enabled
            and source == "inside"
            and door_id in ("rearLeft", "rearRight")
        ):
            msg = f"Unlock BLOCKED for {door_id.upper()} from INSIDE"
            print(msg)
            logger.info(msg)

            self._publish_event(
                {
                    "event": "child_mode_blocked_rear_inside_unlock",
                    "door": door_id.upper(),
                }
            )
            # Note: We intentionally do NOT forward this unlock command.
            return

        # Otherwise just log / allow (no extra publish needed here)
        msg = f"Unlock ALLOWED for {door_id.upper()} from {source.upper()}"
        print(msg)
        logger.info(msg)

    def handle_safety_door(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except Exception:
            logger.warning("Malformed door payload: %r", payload)
            return

        moving = bool(data.get("moving", False))
        speed_kph = float(data.get("speedKph", 0.0))
        any_open = bool(data.get("anyOpen", False))
        open = data.get("open", [])

        self.moving = moving
        self.last_speed_kph = speed_kph
        self.any_door_open = any_open

        logger.debug(
            "SafetyDoor: moving=%s speed=%.1f anyOpen=%s",
            moving,
            speed_kph,
            any_open,
        )

        # Child mode speed limit alert
        if self.child_mode_enabled and speed_kph > CHILD_MODE_MAX_SPEED_KPH:
            self._publish_event(
                {
                    "event": "child_mode_speed_exceeded",
                    "speedKph": speed_kph,
                    "limitKph": CHILD_MODE_MAX_SPEED_KPH,
                }
            )
            
        if self.child_mode_enabled and moving and any_open:
            self._publish_event(
                {
                    "event": "child_mode_unfastened_seatbelt",
                    "speedKph": speed_kph,
                    "any_door_open": open,
                }
            )

    def handle_safety_seatbelt(self, payload: str) -> None:
        try:
            data = json.loads(payload)
        except Exception:
            logger.warning("Malformed seatbelt payload: %r", payload)
            return

        moving = bool(data.get("moving", False))
        speed_kph = float(data.get("speedKph", 0.0))
        any_unfastened = bool(data.get("anyUnfastened", False))
        unfastened = data.get("unfastened", [])

        self.moving = moving
        self.last_speed_kph = speed_kph
        self.any_unfastened = any_unfastened

        logger.debug(
            "SafetySeatbelt: moving=%s speed=%.1f anyUnfastened=%s",
            moving,
            speed_kph,
            any_unfastened,
        )
        
        if self.child_mode_enabled and speed_kph > CHILD_MODE_MAX_SPEED_KPH:
            self._publish_event(
                {
                    "event": "child_mode_speed_exceeded",
                    "speedKph": speed_kph,
                    "limitKph": CHILD_MODE_MAX_SPEED_KPH,
                }
            )

        # Only alert when: child mode ON, vehicle moving, and belts not all fastened
        if self.child_mode_enabled and moving and any_unfastened:
            self._publish_event(
                {
                    "event": "child_mode_unfastened_seatbelt",
                    "speedKph": speed_kph,
                    "unfastened": unfastened,
                }
            )
            
    def handle_safety_speed(self, payload: str) -> None:
        """
        Handle raw speed updates from SafetyApp:
          topic: ext/safety/speed
          payload example: {"speedKph": 42.5}
        """
        try:
            data = json.loads(payload)
        except Exception:
            logger.warning("Malformed speed payload: %r", payload)
            return

        speed_kph = float(data.get("speedKph", 0.0))
        self.last_speed_kph = speed_kph

        logger.debug("SafetySpeed: speed=%.1f km/h", speed_kph)

        # Check child-mode speed limit immediately on each update
        if self.child_mode_enabled and speed_kph > CHILD_MODE_MAX_SPEED_KPH:
            self._publish_event(
                {
                    "event": "child_mode_speed_exceeded",
                    "speedKph": speed_kph,
                    "limitKph": CHILD_MODE_MAX_SPEED_KPH,
                }
            )

def main() -> None:
    client = mqtt.Client()
    controller = ChildLockController(client)

    def on_connect(client: mqtt.Client, userdata, flags, rc: int) -> None:
        print(f"Connected to MQTT with rc = {rc}")
        logger.info("Connected to MQTT broker %s:%s rc=%s", BROKER_HOST, BROKER_PORT, rc)

        # Subscribe to child mode control, unlock commands, and safety aggregates
        client.subscribe(TOPIC_CHILDLOCK_SET, qos=1)
        client.subscribe(DOOR_UNLOCK_PATTERN, qos=1)
        client.subscribe(TOPIC_SAFETY_DOOR, qos=1)
        client.subscribe(TOPIC_SAFETY_SEATBELT, qos=1)
        client.subscribe(TOPIC_SAFETY_SPEED, qos=1)


    def on_message(client: mqtt.Client, userdata, msg: mqtt.MQTTMessage) -> None:
        topic = msg.topic
        payload = msg.payload.decode(errors="ignore")

        if topic == TOPIC_CHILDLOCK_SET:
            controller.handle_childlock_set(payload)
        elif topic == TOPIC_SAFETY_DOOR:
            controller.handle_safety_door(payload)
        elif topic == TOPIC_SAFETY_SEATBELT:
            controller.handle_safety_seatbelt(payload)
        elif topic == TOPIC_SAFETY_SPEED:
            controller.handle_safety_speed(payload)
        elif topic.startswith("ext/doors/") and topic.endswith("/unlock"):
            controller.handle_unlock_request(topic, payload)
        else:
            logger.debug("Ignoring message on %s", topic)


    client.on_connect = on_connect
    client.on_message = on_message

    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    client.loop_forever()


if __name__ == "__main__":
    main()
