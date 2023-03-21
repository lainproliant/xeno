# --------------------------------------------------------------------
# events.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Thursday March 9, 2023
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

"""
Asynchronous event dispatch and broadcast.
"""

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Generator, Optional

from xeno.utils import async_wrap


# --------------------------------------------------------------------
@dataclass
class Event:
    name: str
    context: Any = None
    data: Any = None
    when: datetime = field(default_factory=datetime.now)

    def age(self) -> timedelta:
        return datetime.now() - self.when


# --------------------------------------------------------------------
EventListener = Callable[[Event], Awaitable]

# --------------------------------------------------------------------
class EventBus:
    _current_bus: Optional["EventBus"] = None

    class _Session:
        def __init__(self):
            self.bus = EventBus()

        def __enter__(self):
            EventBus._current_bus = self.bus

        def __exit__(self):
            EventBus._current_bus = None
            self.bus.shutdown_flag.set()

    @staticmethod
    def session():
        return EventBus._Session()

    @staticmethod
    def get():
        if EventBus._current_bus is None:
            raise ValueError("There is no current event bus session.")
        return EventBus._current_bus

    def __init__(self):
        self.queue: asyncio.Queue[Event] = asyncio.Queue()
        self.shutdown_flag = asyncio.Event()
        self.broadcast_listeners: set[EventListener] = set()
        self.subscriptions: defaultdict[str, set[EventListener]] = defaultdict(
            lambda: set()
        )

    def send(self, event: Event):
        self.queue.put_nowait(event)

    def shutdown(self):
        self.shutdown_flag.set()

    def listen(self, listener: EventListener):
        self.broadcast_listeners.add(listener)

    def unlisten(self, listener: EventListener):
        try:
            self.broadcast_listeners.remove(listener)
        except KeyError:
            pass

    def subscribe(self, event: str, listener: EventListener):
        self.subscriptions[event].add(listener)

    def unsubscribe(self, event: str, listener: EventListener):
        subs = self.subscriptions[event]
        try:
            subs.remove(listener)
        except KeyError:
            pass

        if not subs:
            del self.subscriptions[event]

    async def run(self):
        while not self.shutdown_flag.is_set():
            event = self.queue.get_nowait()
            if event is not None:
                await self._dispatch(event)
            await asyncio.sleep(0)

    def _listeners_for_event(
        self, event: Event
    ) -> Generator[EventListener, None, None]:
        yield from self.broadcast_listeners
        if event.name in self.subscriptions:
            yield from self.subscriptions[event.name]

    async def _dispatch(self, event: Event):
        await asyncio.gather(
            *(
                async_wrap(listener, event)
                for listener in self._listeners_for_event(event)
            )
        )
