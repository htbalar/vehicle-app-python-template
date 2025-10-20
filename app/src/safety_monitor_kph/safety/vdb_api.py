# app/src/safety_monitor_kph/safety/vdb_api.py
from typing import Dict, List, Tuple, Callable, Awaitable
import logging

log = logging.getLogger("safety.discovery")

class VdbApi:
    def __init__(self, vehicle):
        self.Vehicle = vehicle
        self._belt_readers: List[Tuple[str, Callable[[], Awaitable]]] = []
        self._door_readers: List[Tuple[str, Callable[[], Awaitable[bool]]]] = []

    async def get_speed_kph(self) -> float:
        return (await self.Vehicle.Speed.get()).value

    async def _try_bool(self, getter: Callable[[], Awaitable]):
        try:
            val = (await getter()).value
            return True, bool(val)
        except Exception:
            return False, False

    async def get_seatbelts_map(self) -> Dict[str, bool]:
        belts: Dict[str, bool] = {}

        # Discover once
        if not self._belt_readers:
            candidates: List[Tuple[str, Callable[[], Awaitable]]] = [
                ("Row1.DriverSide", lambda: self.Vehicle.Cabin.Seat.Row1.DriverSide.Belt.IsFastened.get()),
                ("Row1.PassengerSide", lambda: self.Vehicle.Cabin.Seat.Row1.PassengerSide.Belt.IsFastened.get()),
                ("Row1.Pos1", lambda: self.Vehicle.Cabin.Seat.Row1.Pos1.Belt.IsFastened.get()),
                ("Row1.Pos2", lambda: self.Vehicle.Cabin.Seat.Row1.Pos2.Belt.IsFastened.get()),
                # Add Row2.* variants if your catalog supports them
            ]
            found = []
            for name, getter in candidates:
                ok, _ = await self._try_bool(getter)
                if ok:
                    self._belt_readers.append((name, getter))
                    found.append(name)
            if found:
                log.info("Discovered seatbelt signals: %s", found)
            else:
                log.info("No seatbelt signals discovered in this VSS catalog.")

        for name, getter in self._belt_readers:
            ok, val = await self._try_bool(getter)
            if ok:
                belts[name] = val

        return belts

    async def get_doors_closed_map(self) -> Dict[str, bool]:
        """
        Return a dict of door states normalized to 'is closed = True'.
        Supports catalogs with either IsClosed or IsOpen.
        """
        doors: Dict[str, bool] = {}

        if not self._door_readers:
            def reader_factory(label: str, closed_getter=None, open_getter=None):
                async def read() -> bool:
                    if closed_getter:
                        return bool((await closed_getter()).value)
                    elif open_getter:
                        return not bool((await open_getter()).value)  # invert IsOpen -> IsClosed
                    raise RuntimeError("No getter")
                return (label, read)

            candidates: List[Tuple[str, Callable[[], Awaitable[bool]]]] = []

            # Try common positions; add/remove as your catalog needs
            # Front left
            try:
                candidates.append(reader_factory(
                    "frontLeft",
                    closed_getter=self.Vehicle.Body.Door.Row1.Left.IsClosed.get
                ))
            except Exception:
                try:
                    candidates.append(reader_factory(
                        "frontLeft",
                        open_getter=self.Vehicle.Body.Door.Row1.Left.IsOpen.get
                    ))
                except Exception:
                    pass

            # Front right
            try:
                candidates.append(reader_factory(
                    "frontRight",
                    closed_getter=self.Vehicle.Body.Door.Row1.Right.IsClosed.get
                ))
            except Exception:
                try:
                    candidates.append(reader_factory(
                        "frontRight",
                        open_getter=self.Vehicle.Body.Door.Row1.Right.IsOpen.get
                    ))
                except Exception:
                    pass

            # Rear left
            try:
                candidates.append(reader_factory(
                    "rearLeft",
                    closed_getter=self.Vehicle.Body.Door.Row2.Left.IsClosed.get
                ))
            except Exception:
                try:
                    candidates.append(reader_factory(
                        "rearLeft",
                        open_getter=self.Vehicle.Body.Door.Row2.Left.IsOpen.get
                    ))
                except Exception:
                    pass

            # Rear right
            try:
                candidates.append(reader_factory(
                    "rearRight",
                    closed_getter=self.Vehicle.Body.Door.Row2.Right.IsClosed.get
                ))
            except Exception:
                try:
                    candidates.append(reader_factory(
                        "rearRight",
                        open_getter=self.Vehicle.Body.Door.Row2.Right.IsOpen.get
                    ))
                except Exception:
                    pass

            found = []
            for label, read in candidates:
                try:
                    _ = await read()   # probe
                    self._door_readers.append((label, read))
                    found.append(label)
                except Exception:
                    pass

            if found:
                log.info("Discovered door signals: %s", found)
            else:
                log.warning("No door signals discovered in this VSS catalog.")

        for label, read in self._door_readers:
            try:
                doors[label] = bool(await read())
            except Exception:
                pass

        return doors
