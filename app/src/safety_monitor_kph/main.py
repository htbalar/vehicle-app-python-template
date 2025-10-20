import asyncio
import logging
import os
import signal

# --- Import the generated Vehicle as a DISTINCT name ---
try:
    # In a real Velocitas workspace this exists
    from vehicle import Vehicle as GeneratedVehicle  # type: ignore
except Exception:
    # Minimal runtime stub so the app can still start without the generated client
    class _DummySignal:
        async def get(self):
            class _V:
                value = 0.0
            return _V()

    class GeneratedVehicle:  # pragma: no cover
        def __init__(self, *_args, **_kwargs):
            pass  # accept any signature for local smoke tests
        Speed = _DummySignal()
        class Cabin:
            class Seat:
                class Row1:
                    class DriverSide:
                        class Belt:
                            IsFastened = _DummySignal()
                    class PassengerSide:
                        class Belt:
                            IsFastened = _DummySignal()
        class Body:
            class Door:
                class Row1:
                    class Left:
                        IsClosed = _DummySignal()
                    class Right:
                        IsClosed = _DummySignal()
                class Row2:
                    class Left:
                        IsClosed = _DummySignal()
                    class Right:
                        IsClosed = _DummySignal()

from safety_monitor_kph.safety_app import SafetyApp

log = logging.getLogger("launcher")
logging.basicConfig(level=logging.INFO)


def _create_vehicle_client():
    """Handle both Vehicle(name: str) and Vehicle() constructor variants."""
    preferred_name = os.getenv("VEHICLE_INSTANCE_NAME", "safety-monitor")
    try:
        # Most Velocitas templates require a name
        return GeneratedVehicle(preferred_name)  # type: ignore[misc]
    except TypeError:
        # Some generated clients may not need args
        return GeneratedVehicle()  # type: ignore[call-arg]


async def _main() -> None:
    vehicle_client = _create_vehicle_client()
    app = SafetyApp(vehicle_client)
    await app.run()


if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, loop.stop)
        except Exception:
            pass
    try:
        loop.run_until_complete(_main())
    finally:
        loop.close()
