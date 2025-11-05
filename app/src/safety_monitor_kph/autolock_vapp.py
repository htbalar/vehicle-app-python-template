

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Optional

from vehicle import Vehicle  # type: ignore

from velocitas_sdk.vdb.reply import DataPointReply  # type: ignore
from velocitas_sdk.vehicle_app import VehicleApp, subscribe_topic  # type: ignore

# -------- Configuration (env with sensible defaults) --------

LOCK_ABOVE_KPH = float(os.getenv("AUTOLOCK_LOCK_ABOVE_KPH", "5.0"))
UNLOCK_BELOW_KPH = float(os.getenv("AUTOLOCK_UNLOCK_BELOW_KPH", "3.0"))

TOPIC_LOCK_CMD = os.getenv("MQTT_TOPIC_LOCK_CMD", "vehicle/lockDoors")
TOPIC_UNLOCK_CMD = os.getenv("MQTT_TOPIC_UNLOCK_CMD", "vehicle/unlockDoors")

TOPIC_CFG_SET = os.getenv("MQTT_TOPIC_AUTOLOCK_CFG_SET", "safety/config/autolock/set")
TOPIC_CFG_STATE = os.getenv("MQTT_TOPIC_AUTOLOCK_CFG_STATE", "ext/safety/config/autolock")

TOPIC_DOOR_STATUS = os.getenv("MQTT_TOPIC_DOOR_STATUS", "ext/safety/door")

STATE_FILE = os.getenv(
    "AUTOLOCK_STATE_FILE", "app/src/safety_monitor_kph/config/autolock.json"
)

# ------------------------------------------------------------

logger = logging.getLogger(__name__)
logging.getLogger().setLevel("DEBUG")


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _load_enabled_from_file(path: Path) -> Optional[bool]:
    try:
        with path.open("r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and isinstance(data.get("enabled"), bool):
            return data["enabled"]
    except FileNotFoundError:
        return None
    except Exception as exc:
        logger.warning("Failed to read %s: %s", path, exc)
    return None


def _persist_enabled_to_file(path: Path, enabled: bool) -> None:
    try:
        _ensure_parent(path)
        with path.open("w", encoding="utf-8") as f:
            json.dump({"enabled": enabled}, f, indent=2)
    except Exception as exc:
        logger.warning("Failed to write %s: %s", path, exc)


class AutoLockApp(VehicleApp):
    """
    Smart Auto-Lock VehicleApp.

    Hysteresis:
      - Lock when speed crosses above LOCK_ABOVE_KPH.
      - Unlock when speed falls below UNLOCK_BELOW_KPH.
    """

    def __init__(self, vehicle_client: Vehicle):
        super().__init__()
        self.Vehicle = vehicle_client

        # Load persisted "enabled" or fallback to env default
        persisted = _load_enabled_from_file(Path(STATE_FILE))
        self.enabled: bool = (
            persisted
            if persisted is not None
            else (os.getenv("AUTOLOCK_ENABLED", "true").lower() == "true")
        )

        # Internal latch so we only publish on transitions
        self._locked_state: Optional[str] = None
        self._pending_lock: bool = False
        self._any_door_open: bool = False # "locked" | "unlocked" | None

        logger.info(
            "AutoLockApp init: enabled=%s lock_above=%.2f unlock_below=%.2f",
            self.enabled,
            LOCK_ABOVE_KPH,
            UNLOCK_BELOW_KPH,
        )

    async def on_start(self) -> None:
        """Called by VehicleApp when the app starts."""
        # Subscribe to speed updates from KUKSA
        await self.Vehicle.Speed.subscribe(self._on_speed_changed)
        logger.info("AutoLockApp: subscribed to SELECT %s.Speed", "Vehicle")
        logger.info("AutoLockApp: listening to door status on %s", TOPIC_DOOR_STATUS)


        # Publish current config state so UIs/tools can see it
        await self._publish_enabled_state()

        logger.info(
            "AutoLockApp started with enabled=%s (cfg topics: set=%s, state=%s)",
            self.enabled,
            TOPIC_CFG_SET,
            TOPIC_CFG_STATE,
        )

    async def _on_speed_changed(self, data: DataPointReply) -> None:
        """Handle Vehicle.Speed updates with hysteresis-based + pending-lock state machine."""
        try:
            speed = data.get(self.Vehicle.Speed).value  # km/h
        except Exception:
            return

        if speed is None:
            return

        logger.debug(
            "AutoLockApp: speed=%.2f km/h enabled=%s state=%s anyDoorOpen=%s pending=%s",
            float(speed or 0.0),
            self.enabled,
            self._locked_state,
            self._any_door_open,
            self._pending_lock,
        )

        # Ignore if feature disabled
        if not self.enabled:
            return

        # --- LOCK side (with pending-lock logic) ---
        if speed > LOCK_ABOVE_KPH:
            # Case 1: moving, but some doors open → defer lock
            if self._any_door_open:
                if not self._pending_lock:
                    logger.info("AutoLock: deferring LOCK (doors open) -> pending_lock=True")
                self._pending_lock = True
                return

            # Case 2: moving and doors closed → perform lock (if not locked)
            if self._locked_state != "locked":
                await self._publish_lock()
                self._locked_state = "locked"
                self._pending_lock = False
            return

        # --- UNLOCK side (standard hysteresis) ---
        if speed < UNLOCK_BELOW_KPH:
            if self._locked_state != "unlocked":
                await self._publish_unlock()
                self._locked_state = "unlocked"
            # Clear pending if vehicle slowed down
            self._pending_lock = False
            return
        
    @subscribe_topic(TOPIC_DOOR_STATUS)
    async def on_door_status(self, payload: str) -> None:
        """
        Listen to Safety app's aggregate door status:
        topic: ext/safety/door
        examples:
            {"moving": true, "anyOpen": true, "open": ["frontLeft"], "state": "active"}
            {"moving": true, "anyOpen": false, "open": [], "state": "cleared"}
        Drives pending-lock so that locking occurs as soon as all doors are closed while moving.
        """
        # Parse incoming status
        try:
            data = json.loads(payload)
            any_open = bool(data.get("anyOpen", False))
        except Exception:
            return  # ignore malformed messages

        # Remember latest aggregate door state
        self._any_door_open = any_open

        # Read current speed (for robust decisions even if speed event came earlier)
        try:
            speed_reply = await self.Vehicle.Speed.get()
            speed_now = speed_reply.value
        except Exception:
            speed_now = None

        # If doors opened while already moving and not locked -> set pending_lock
        if (
            any_open
            and speed_now is not None
            and speed_now > LOCK_ABOVE_KPH
            and self._locked_state != "locked"
        ):
            if not self._pending_lock:
                logger.info("AutoLock: doors opened while moving -> pending_lock=True")
            self._pending_lock = True
            return

        # If we were pending and doors just became closed while still moving -> lock now
        if (
            self._pending_lock
            and not any_open
            and speed_now is not None
            and speed_now > LOCK_ABOVE_KPH
        ):
            logger.info("AutoLock: doors closed while moving -> executing pending LOCK")
            await self._publish_lock()
            self._locked_state = "locked"
            self._pending_lock = False




    @subscribe_topic(TOPIC_CFG_SET)
    async def on_cfg_set(self, payload: str) -> None:
        """
        Handle runtime toggle of autolock via MQTT:
          - topic: safety/config/autolock/set
          - payload: "true" | "false" (also accepts JSON true/false)
        """
        new_enabled: Optional[bool] = None
        raw = payload.strip().lower()

        # Accept plain strings or JSON boolean
        if raw in ("true", "false"):
            new_enabled = (raw == "true")
        else:
            # try JSON parse
            try:
                v = json.loads(payload)
                if isinstance(v, bool):
                    new_enabled = v
            except Exception:
                pass

        if new_enabled is None:
            logger.warning(
                "Invalid payload on %s: %r (expected true/false)", TOPIC_CFG_SET, payload
            )
            return

        if new_enabled == self.enabled:
            logger.debug("Autolock already %s; ignoring", new_enabled)
            # Still publish state so subscribers see a heartbeat
            await self._publish_enabled_state()
            return

        self.enabled = new_enabled
        _persist_enabled_to_file(Path(STATE_FILE), self.enabled)
        logger.info("Autolock set to %s (persisted to %s)", self.enabled, STATE_FILE)
        await self._publish_enabled_state()

    # ------------- helpers -------------

    async def _publish_enabled_state(self) -> None:
        await self.publish_event(
            TOPIC_CFG_STATE, json.dumps({"enabled": self.enabled})
        )

    async def _publish_lock(self) -> None:
        logger.info("AutoLock: LOCK command -> %s (speed > %.2f)", TOPIC_LOCK_CMD, LOCK_ABOVE_KPH)
        await self.publish_event(TOPIC_LOCK_CMD, json.dumps({"command": "lock"}))

    async def _publish_unlock(self) -> None:
        logger.info(
            "AutoLock: UNLOCK command -> %s (speed < %.2f)", TOPIC_UNLOCK_CMD, UNLOCK_BELOW_KPH
        )
        await self.publish_event(TOPIC_UNLOCK_CMD, json.dumps({"command": "unlock"}))
