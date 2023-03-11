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


# --------------------------------------------------------------------
class EventBusContainer:
    def __init__(self):
        self.bus: Optional[EventBus] = None

    def set_event_bus(self, bus: EventBus):
        self.bus = bus

    def get_event_bus(self) -> EventBus:
        if not self.bus:
            raise ValueError("There is no event bus set.")
        return self.bus

    def setup_events(self):
        if not self.bus:
            self.bus = EventBus()

    def send_event(self, name: str, ctx: Any = None, data: Any = None):
        if self.bus is None:
            return
        self.bus.send(Event(name, ctx, data))

    def listen_events(self, listener: EventListener):
        self.get_event_bus().listen(listener)

    def unlisten_events(self, listener: EventListener):
        self.get_event_bus().unlisten(listener)

    def subscribe_event(self, name: str, listener: EventListener):
        self.get_event_bus().subscribe(name, listener)

    def unsubscribe_event(self, name: str, listener: EventListener):
        self.get_event_bus().unsubscribe(name, listener)


_CONTAINER = EventBusContainer()
setup_events = _CONTAINER.setup_events
set_event_bus = _CONTAINER.set_event_bus
get_event_bus = _CONTAINER.get_event_bus
send_event = _CONTAINER.send_event
listen_events = _CONTAINER.listen_events
unlisten_events = _CONTAINER.unlisten_events
subscribe_event = _CONTAINER.subscribe_event
unsubscribe_event = _CONTAINER.unsubscribe_event
