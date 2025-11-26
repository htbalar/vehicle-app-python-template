# Copyright (c) 2025 Contributors
# SPDX-License-Identifier: Apache-2.0

import json
import logging
import os
from dataclasses import dataclass
from typing import Dict, Optional

from vehicle import Vehicle  # type: ignore

from velocitas_sdk.util.log import (  # type: ignore
    get_opentelemetry_log_factory,
    get_opentelemetry_log_format,
)
from velocitas_sdk.vdb.reply import DataPointReply  # type: ignore
from velocitas_sdk.vehicle_app import VehicleApp, subscribe_topic  # type: ignore

logging.setLogRecordFactory(get_opentelemetry_log_factory())
logging.basicConfig(format=get_opentelemetry_log_format())
logging.getLogger().setLevel("DEBUG")
logger = logging.getLogger(__name__)

# ---- debounce helpers ----
@dataclass
class _DebouncedState:
    active: bool = False
    up: int = 0
    down: int = 0

def _tick(st: _DebouncedState, condition: bool, debounce_count: int) -> Optional[str]:
    """Return 'activated' | 'cleared' | None when debounced transitions happen."""
    if condition:
        st.up += 1; st.down = 0
        if not st.active and st.up >= debounce_count:
            st.active = True
            return "activated"
    else:
        st.down += 1; st.up = 0
        if st.active and st.down >= debounce_count:
            st.active = False
            return "cleared"
    return None

class SafetyApp(VehicleApp):
    """
    Safety monitor (Velocitas VehicleApp):
    - Reads Vehicle.Speed from the Data Broker (km/h).
    - Listens on MQTT for door/seatbelt inputs to keep your CLI workflow simple.
    - Publishes alerts to ext/safety/door and ext/safety/seatbelt.
    """

    def __init__(self, vehicle_client: Vehicle):
        super().__init__()
        self.Vehicle = vehicle_client

        # Config (km/h)
        self.threshold_kph: float = float(os.getenv("SAFETY_SPEED_THRESHOLD_KPH", "5"))
        self.debounce_count: int = int(os.getenv("SAFETY_DEBOUNCE_COUNT", "1"))
        self.topic_seatbelt = os.getenv("TOPIC_SEATBELT", "ext/safety/seatbelt")
        self.topic_door = os.getenv("TOPIC_DOOR", "ext/safety/door")
        self.topic_speed = os.getenv("TOPIC_SPEED", "ext/safety/speed")

        # Runtime state
        self.speed_kph: float = 0.0
        self.doors_open: Dict[str, bool] = {
            "frontLeft": False, "frontRight": False,
            "rearLeft": False, "rearRight": False,
        }
        self.belts_fastened: Dict[str, bool] = {
            "row1_pos1": True, "row1_pos2": True,
        }

        # Debounced states
        self._sb_state = _DebouncedState()
        self._door_state = _DebouncedState()

        # NEW: Track last published aggregates so we can republish updates while active
        self._last_open_doors: set[str] = set()
        self._last_unfastened: set[str] = set()
        self._last_moving: bool = False


    # -------------------- lifecycle --------------------
    async def on_start(self):
        """Subscribe to Vehicle.Speed changes from the Data Broker."""
        await self.Vehicle.Speed.subscribe(self.on_speed_changed)
        logger.info(
            "SafetyApp started with threshold_kph=%s debounce=%s",
            self.threshold_kph, self.debounce_count
        )
        # Optionally publish current config
        await self.publish_event("ext/safety/config", json.dumps({
            "thresholdKph": self.threshold_kph,
            "debounce": self.debounce_count
        }))

    async def on_speed_changed(self, data: DataPointReply):
        self.speed_kph = data.get(self.Vehicle.Speed).value
        try:
            speed_val = float(self.speed_kph or 0.0)
        except Exception:
            speed_val = 0.0

        await self.publish_event(
            self.topic_speed,
            json.dumps({"speedKph": round(speed_val, 1)})
        )
        await self._evaluate_and_publish()

    # -------------------- MQTT inputs (same CLI style you used) --------------------
    @subscribe_topic("safety/input/door/frontLeft")
    async def _on_door_front_left(self, payload: str):
        self.doors_open["frontLeft"] = _parse_bool(payload)
        await self._evaluate_and_publish()

    @subscribe_topic("safety/input/door/frontRight")
    async def _on_door_front_right(self, payload: str):
        self.doors_open["frontRight"] = _parse_bool(payload)
        await self._evaluate_and_publish()

    @subscribe_topic("safety/input/door/rearLeft")
    async def _on_door_rear_left(self, payload: str):
        self.doors_open["rearLeft"] = _parse_bool(payload)
        await self._evaluate_and_publish()

    @subscribe_topic("safety/input/door/rearRight")
    async def _on_door_rear_right(self, payload: str):
        self.doors_open["rearRight"] = _parse_bool(payload)
        await self._evaluate_and_publish()

    @subscribe_topic("safety/input/seatbelt/row1_pos1")
    async def _on_belt_row1_pos1(self, payload: str):
        self.belts_fastened["row1_pos1"] = _parse_bool(payload)
        await self._evaluate_and_publish()

    @subscribe_topic("safety/input/seatbelt/row1_pos2")
    async def _on_belt_row1_pos2(self, payload: str):
        self.belts_fastened["row1_pos2"] = _parse_bool(payload)
        await self._evaluate_and_publish()

    # -------------------- core evaluation --------------------
    async def _evaluate_and_publish(self):
        moving = self.speed_kph > self.threshold_kph
        unfastened = [k for k, fastened in self.belts_fastened.items() if not fastened]
        open_doors = [k for k, is_open in self.doors_open.items() if is_open]

        sb_change = _tick(self._sb_state, moving and bool(unfastened), self.debounce_count)
        dr_change = _tick(self._door_state, moving and bool(open_doors), self.debounce_count)

        # ---------- Seatbelt ----------
        seatbelt_should_update = False
        if sb_change is not None:
            seatbelt_should_update = True
        elif self._sb_state.active and (
            set(unfastened) != self._last_unfastened or moving != self._last_moving
        ):
            seatbelt_should_update = True

        if seatbelt_should_update:
            payload = {
                "moving": moving,
                "speedKph": round(float(self.speed_kph or 0.0), 1),
                "anyUnfastened": bool(unfastened),
                "unfastened": unfastened,
                "thresholdKph": self.threshold_kph,
                "state": "active" if self._sb_state.active else "cleared",
            }
            await self.publish_event(self.topic_seatbelt, json.dumps(payload))
            logger.info("Seatbelt %s %s", payload["state"], payload)
            self._last_unfastened = set(unfastened)

        # ---------- Doors ----------
        door_should_update = False
        if dr_change is not None:
            door_should_update = True
        elif self._door_state.active and (
            set(open_doors) != self._last_open_doors or moving != self._last_moving
        ):
            door_should_update = True

        if door_should_update:
            payload = {
                "moving": moving,
                "speedKph": round(float(self.speed_kph or 0.0), 1),
                "anyOpen": bool(open_doors),
                "open": open_doors,
                "thresholdKph": self.threshold_kph,
                "state": "active" if self._door_state.active else "cleared",
            }
            await self.publish_event(self.topic_door, json.dumps(payload))
            logger.info("Door %s %s", payload["state"], payload)
            self._last_open_doors = set(open_doors)

        self._last_moving = moving



def _parse_bool(s: str) -> bool:
    s = s.strip().lower()
    if s in ("true", "1", "on", "yes"): return True
    if s in ("false", "0", "off", "no"): return False
    try:
        return bool(json.loads(s))
    except Exception:
        return False
