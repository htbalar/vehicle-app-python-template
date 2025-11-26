import asyncio
import logging
import os
import signal

from vehicle import Vehicle  # type: ignore
from safety_monitor_kph.safety_vapp import SafetyApp  # type: ignore

logging.getLogger().setLevel("DEBUG")

async def _main():
    instance_name = os.getenv("VEHICLE_INSTANCE_NAME", "Vehicle")
    try:
        app = SafetyApp(Vehicle(instance_name)) 
    except TypeError:
        app = SafetyApp(Vehicle())               # type: ignore
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
