import asyncio
import json
import logging
from typing import Any

from safety_monitor_kph.safety.config import get_config
from safety_monitor_kph.safety.monitor import SafetyMonitor
from safety_monitor_kph.safety.vdb_api import VdbApi

# Use the real VehicleApp if available; otherwise provide a tiny stub for local runs
try:
    from velocitas_sdk.vehicle_app import VehicleApp  # type: ignore
except Exception:
    class VehicleApp:  # pragma: no cover
        async def publish_event(self, topic: str, payload: str) -> None:
            print(f"[MQTT] {topic}: {payload}")

log = logging.getLogger("safety")
logging.basicConfig(level=logging.INFO)

class SafetyApp(VehicleApp):
    def __init__(self, vehicle: Any) -> None:
        """
        Accept 'Any' so we can pass either the generated Vehicle client or a stub.
        """
        super().__init__()
        self.cfg = get_config()
        self.vdb = VdbApi(vehicle)
        log.info("Probing VSS for seatbelts/doors… (first read will log what is available)")

        self.monitor = SafetyMonitor(self.cfg)

    async def run(self) -> None:
        tick = self.cfg["TICK_MS"] / 1000.0
        log.info("SafetyApp starting with cfg=%s", self.cfg)

        while True:
            speed = await self.vdb.get_speed_kph()
            belts = await self.vdb.get_seatbelts_map()
            doors = await self.vdb.get_doors_closed_map()

            sb_change, dr_change, status = self.monitor.evaluate(speed, belts, doors)

            if sb_change:
                payload = {
                    "moving": status.moving,
                    "anyUnfastened": bool(status.unfastened),
                    "unfastened": status.unfastened,
                    "thresholdKph": status.threshold_kph,
                    "state": "active" if sb_change == "activated" else "cleared",
                }
                await self.publish_event(self.cfg["TOPIC_SEATBELT"], json.dumps(payload))
                log.info("Seatbelt %s: %s", payload["state"], payload)

            if dr_change:
                payload = {
                    "moving": status.moving,
                    "anyOpen": bool(status.open_doors),
                    "open": status.open_doors,
                    "thresholdKph": status.threshold_kph,
                    "state": "active" if dr_change == "activated" else "cleared",
                }
                await self.publish_event(self.cfg["TOPIC_DOOR"], json.dumps(payload))
                log.info("Door %s: %s", payload["state"], payload)

            await asyncio.sleep(tick)
