import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, Optional, List

import paho.mqtt.client as mqtt

log = logging.getLogger("safety.mqtt")
logging.basicConfig(level=logging.INFO)

# ---------- Debounce + logic (same behavior as VSS version) ----------
@dataclass
class DebouncedState:
    active: bool = False
    up: int = 0
    down: int = 0

@dataclass
class SafetyStatus:
    moving: bool
    threshold_kph: float
    unfastened: List[str] = field(default_factory=list)
    open_doors: List[str] = field(default_factory=list)

class SafetyLogic:
    def __init__(self, threshold_kph: float, debounce: int):
        self.threshold_kph = threshold_kph
        self.debounce = debounce
        self._seatbelt_state = DebouncedState()
        self._door_state = DebouncedState()

    def evaluate(self, speed_kph: float, belts: Dict[str, bool], doors_open: Dict[str, bool]):
        moving = speed_kph > self.threshold_kph
        unfastened = [k for k, fastened in belts.items() if not fastened]
        open_doors = [k for k, is_open in doors_open.items() if is_open]

        sb_changed = self._update(self._seatbelt_state, moving and bool(unfastened))
        dr_changed = self._update(self._door_state, moving and bool(open_doors))

        return sb_changed, dr_changed, SafetyStatus(moving, self.threshold_kph, unfastened, open_doors)

    def _update(self, st: DebouncedState, condition: bool) -> Optional[str]:
        if condition:
            st.up += 1; st.down = 0
            if not st.active and st.up >= self.debounce:
                st.active = True
                return "activated"
        else:
            st.down += 1; st.up = 0
            if st.active and st.down >= self.debounce:
                st.active = False
                return "cleared"
        return None

# ---------- MQTT app ----------
class SafetyMqttApp:
    def __init__(self):
        # Config
        self.broker_host = os.getenv("MQTT_HOST", "127.0.0.1")
        self.broker_port = int(os.getenv("MQTT_PORT", "1883"))
        self.threshold_kph = float(os.getenv("SAFETY_SPEED_THRESHOLD_KPH", "5"))
        self.debounce = int(os.getenv("SAFETY_DEBOUNCE_COUNT", "2"))
        self.tick_ms = int(os.getenv("SAFETY_TICK_MS", "500"))
        self.out_topic_seatbelt = os.getenv("TOPIC_SEATBELT", "ext/safety/seatbelt")
        self.out_topic_door = os.getenv("TOPIC_DOOR", "ext/safety/door")

        # State
        self.speed_kph: float = 0.0
        # doors_open=True means OPEN; False means closed
        self.doors_open: Dict[str, bool] = {
            "frontLeft": False, "frontRight": False, "rearLeft": False, "rearRight": False
        }
        # seatbelt True means FASTENED; False means unfastened
        self.belts: Dict[str, bool] = {"row1_pos1": True, "row1_pos2": True}

        self.logic = SafetyLogic(self.threshold_kph, self.debounce)

        # MQTT client
        self.client = mqtt.Client()
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message

    # MQTT callbacks
    def _on_connect(self, client, userdata, flags, rc):
        log.info("Connected to MQTT broker rc=%s", rc)
        # Subscribe to inputs
        subs = [
            ("safety/input/speed_kph", 0),
            ("safety/input/door/frontLeft", 0),
            ("safety/input/door/frontRight", 0),
            ("safety/input/door/rearLeft", 0),
            ("safety/input/door/rearRight", 0),
            ("safety/input/seatbelt/row1_pos1", 0),
            ("safety/input/seatbelt/row1_pos2", 0),
        ]
        for t, q in subs:
            client.subscribe(t, q)
        log.info("Subscribed to input topics")

    def _parse_bool(self, payload: str) -> bool:
        pl = payload.strip().lower()
        if pl in ("true", "1", "on", "yes"): return True
        if pl in ("false", "0", "off", "no"): return False
        # fallback: try JSON boolean
        try: return bool(json.loads(payload))
        except Exception: return False

    def _on_message(self, client, userdata, msg):
        topic = msg.topic
        payload = msg.payload.decode("utf-8")
        try:
            if topic == "safety/input/speed_kph":
                self.speed_kph = float(payload)
            elif topic.startswith("safety/input/door/"):
                key = topic.split("/")[-1]  # e.g., frontLeft
                self.doors_open[key] = self._parse_bool(payload)
            elif topic.startswith("safety/input/seatbelt/"):
                key = topic.split("/")[-1]  # e.g., row1_pos1
                self.belts[key] = self._parse_bool(payload)
        except Exception as e:
            log.warning("Bad input '%s' on %s: %s", payload, topic, e)

    def _publish(self, topic: str, obj: dict):
        self.client.publish(topic, json.dumps(obj), qos=0, retain=False)

    def connect(self):
        self.client.connect(self.broker_host, self.broker_port, keepalive=60)

    def start_loop_in_thread(self):
        th = threading.Thread(target=self.client.loop_forever, daemon=True)
        th.start()

    def run(self):
        log.info("Starting SafetyMqttApp cfg={kph=%s, debounce=%s, tick_ms=%s}", self.threshold_kph, self.debounce, self.tick_ms)
        self.connect()
        self.start_loop_in_thread()

        tick = self.tick_ms / 1000.0
        while True:
            sb_changed, dr_changed, status = self.logic.evaluate(self.speed_kph, self.belts, self.doors_open)

            if sb_changed:
                payload = {
                    "moving": status.moving,
                    "anyUnfastened": bool(status.unfastened),
                    "unfastened": status.unfastened,
                    "thresholdKph": status.threshold_kph,
                    "state": "active" if sb_changed == "activated" else "cleared",
                }
                self._publish(self.out_topic_seatbelt, payload)
                log.info("Seatbelt %s %s", payload["state"], payload)

            if dr_changed:
                payload = {
                    "moving": status.moving,
                    "anyOpen": bool(status.open_doors),
                    "open": status.open_doors,
                    "thresholdKph": status.threshold_kph,
                    "state": "active" if dr_changed == "activated" else "cleared",
                }
                self._publish(self.out_topic_door, payload)
                log.info("Door %s %s", payload["state"], payload)

            time.sleep(tick)
