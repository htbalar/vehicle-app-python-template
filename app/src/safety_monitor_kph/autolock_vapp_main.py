# Copyright (c) 2025 Contributors
# SPDX-License-Identifier: Apache-2.0

import asyncio
import logging
import os
import signal

from vehicle import Vehicle  # type: ignore
from velocitas_sdk.vehicle_app import VehicleApp  # type: ignore
from velocitas_sdk.util.log import (  # type: ignore
    get_opentelemetry_log_factory,
    get_opentelemetry_log_format,
)

from .autolock_vapp import AutoLockApp  # type: ignore

# Configure logging like the seat-adjuster sample
logging.setLogRecordFactory(get_opentelemetry_log_factory())
logging.basicConfig(format=get_opentelemetry_log_format())
logging.getLogger().setLevel("DEBUG")
logger = logging.getLogger(__name__)


async def _main() -> None:
    vehicle_root = os.getenv("VEHICLE_INSTANCE_NAME", "Vehicle")
    logger.info("Starting AutoLockApp with VEHICLE_INSTANCE_NAME=%s", vehicle_root)

    # Vehicle() in generated client usually takes the root name
    app: VehicleApp = AutoLockApp(Vehicle(vehicle_root))  # type: ignore[arg-type]
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
    except KeyboardInterrupt:
        pass
    finally:
        # Avoid the "Event loop stopped before Future completed." noise on Ctrl+C
        try:
            pending = asyncio.all_tasks(loop)
            for t in pending:
                t.cancel()
            loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
        except Exception:
            pass
        loop.close()
