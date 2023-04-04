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
from enum import Enum
from typing import Any, Callable, Generator, Optional

from xeno.utils import async_wrap


# --------------------------------------------------------------------
class DispatchMode(Enum):
    IMMEDIATE = 0
    ASYNC = 1


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
        self.shutdown_flag = True
        self.sync_listeners.clear()
        self.sync_subs.clear()
        self.async_listeners.clear()
        self.async_subs.clear()
        while not self.queue.empty():
            self.queue.get_nowait()

    def listen(
        self,
        listener: EventListener,
        dispatch_mode=DispatchMode.IMMEDIATE,
    ):
        match dispatch_mode:
            case DispatchMode.IMMEDIATE:
                self.sync_listeners.add(listener)
            case DispatchMode.ASYNC:
                self.async_listeners.add(listener)

    def unlisten(self, listener: EventListener):
        try:
            self.sync_listeners.remove(listener)
        except KeyError:
            pass

        try:
            self.async_listeners.remove(listener)
        except KeyError:
            pass

    def subscribe(
        self, event: str, listener: EventListener, dispatch_mode=DispatchMode.IMMEDIATE
    ):
        match dispatch_mode:
            case DispatchMode.IMMEDIATE:
                self.sync_subs[event].add(listener)
            case DispatchMode.ASYNC:
                self.async_subs[event].add(listener)

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
        while not self.shutdown_flag:
            try:
                event = self.queue.get_nowait()
                await self._dispatch_async(event)

            except asyncio.QueueEmpty:
                pass

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
