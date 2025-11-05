# SPDX-License-Identifier: Apache-2.0
import asyncio
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, List, Optional

import pytest


# ---------- Fakes for Vehicle + DataPointReply ----------

@dataclass
class _Val:
    value: Any

class FakeDataPointReply:
    """Mimic velocitas DataPointReply.get(node).value pattern."""
    def __init__(self, speed_value: float):
        self._speed_value = speed_value

    def get(self, _node):
        return _Val(self._speed_value)

class FakeSpeedNode:
    """Holds a single async callback for subscribe(); supports get()."""
    def __init__(self, initial: float = 0.0):
        self._value = initial
        self._callback: Optional[Callable[[FakeDataPointReply], Awaitable[None]]] = None

    async def subscribe(self, cb):
        self._callback = cb

    async def set_value_and_fire(self, value: float):
        """Simulate a VDB update and invoke the subscribed callback."""
        self._value = value
        if self._callback:
            await self._callback(FakeDataPointReply(value))

    async def get(self):
        return _Val(self._value)

class FakeVehicle:
    """Only the parts the apps use: a .Speed node with subscribe/get."""
    def __init__(self, initial_speed: float = 0.0):
        self.Speed = FakeSpeedNode(initial_speed)


# ---------- Utilities to capture publish_event calls ----------

class PublishCapture:
    """Capture all publish_event(topic, payload) calls."""
    def __init__(self):
        self.events: List[tuple[str, Any]] = []

    async def __call__(self, topic: str, payload: str):
        # Store parsed JSON if possible, otherwise raw string
        try:
            data = json.loads(payload)
        except Exception:
            data = payload
        self.events.append((topic, data))

    def last(self, topic: Optional[str] = None):
        if topic is None:
            return self.events[-1] if self.events else None
        for t, d in reversed(self.events):
            if t == topic:
                return (t, d)
        return None

    def by_topic(self, topic: str) -> List[tuple[str, Any]]:
        return [e for e in self.events if e[0] == topic]


@pytest.fixture
def publish_capture():
    return PublishCapture()

