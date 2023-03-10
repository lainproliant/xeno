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
import inspect
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Callable, Generator, Optional

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
EventListener = Callable[[Event], Any]


# --------------------------------------------------------------------
class EventBus:
    FRAME = "EventBus.FRAME"

    _current_bus: Optional["EventBus"] = None

    class _Session:
        def __init__(self):
            self.bus = EventBus()

        def __enter__(self):
            EventBus._current_bus = self.bus

        def __exit__(self, *_):
            EventBus._current_bus = None
            self.bus.shutdown()

    @staticmethod
    def session() -> "EventBus._Session":
        return EventBus._Session()

    @staticmethod
    def get():
        if EventBus._current_bus is None:
            raise ValueError("There is no current event bus session.")
        return EventBus._current_bus

    def __init__(self):
        self.queue: asyncio.Queue[Event] = asyncio.Queue()
        self.shutdown_flag = asyncio.Event()
        self.async_listeners: set[EventListener] = set()
        self.sync_listeners: set[EventListener] = set()
        self.async_subs: defaultdict[str, set[EventListener]] = defaultdict(set)
        self.sync_subs: defaultdict[str, set[EventListener]] = defaultdict(set)

    def send(self, event: Event):
        if self._has_async_listeners_for_event(event):
            self.queue.put_nowait(event)
        self._dispatch_sync(event)

    def shutdown(self):
        self.shutdown_flag.set()
        self.sync_listeners.clear()
        self.sync_subs.clear()
        self.async_listeners.clear()
        self.async_subs.clear()
        while not self.queue.empty():
            self.queue.get_nowait()

    def listen(self, listener: EventListener):
        if inspect.iscoroutinefunction(listener):
            self.async_listeners.add(listener)
        else:
            self.sync_listeners.add(listener)

    def unlisten(self, listener: EventListener):
        try:
            self.sync_listeners.remove(listener)
        except KeyError:
            pass

        try:
            self.async_listeners.remove(listener)
        except KeyError:
            pass

    def subscribe(self, event: str, listener: EventListener):
        if inspect.iscoroutinefunction(listener):
            self.async_subs[event].add(listener)
        else:
            self.sync_subs[event].add(listener)

    def unsubscribe(self, event: str, listener: EventListener):
        subs = self.sync_subs[event]
        try:
            subs.remove(listener)
        except KeyError:
            pass
        if not subs:
            del self.sync_subs[event]

        subs = self.async_subs[event]
        try:
            subs.remove(listener)
        except KeyError:
            pass
        if not subs:
            del self.async_subs[event]

    async def run(self):
        while not self.shutdown_flag.is_set():
            try:
                event = self.queue.get_nowait()
                await self._dispatch_async(event)

            except asyncio.QueueEmpty:
                pass

            await self._dispatch_frame_event()
            await asyncio.sleep(0)

    def _has_async_listeners_for_event(self, event: Event) -> bool:
        try:
            next(self._async_listeners_for_event(event))
            return True
        except StopIteration:
            return False

    def _async_listeners_for_event(
        self, event: Event
    ) -> Generator[EventListener, None, None]:
        yield from self.async_listeners
        if event.name in self.async_subs:
            yield from self.async_subs[event.name]

    def _sync_listeners_for_event(
        self, event: Event
    ) -> Generator[EventListener, None, None]:
        yield from self.sync_listeners
        if event.name in self.sync_subs:
            yield from self.sync_subs[event.name]

    async def _dispatch_frame_event(self):
        event = Event(EventBus.FRAME, self)
        await self._dispatch_async(event)
        self._dispatch_sync(event)

    def _dispatch_sync(self, event: Event):
        for listener in self._sync_listeners_for_event(event):
            listener(event)

    async def _dispatch_async(self, event: Event):
        await asyncio.gather(
            *(
                async_wrap(listener, event)
                for listener in self._async_listeners_for_event(event)
            )
        )


# --------------------------------------------------------------------
event_session = EventBus.session
