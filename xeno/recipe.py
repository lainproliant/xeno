# --------------------------------------------------------------------
# recipe.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Thursday March 9, 2023
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

import asyncio
import shutil
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Generator, Iterable, Optional

from xeno.events import EventBus, Event
from xeno.shell import Shell
from xeno.utils import async_wrap


# --------------------------------------------------------------------
class Events:
    CLEAN = "clean"
    DEBUG = "debug"
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    START = "start"
    SUCCESS = "success"


# --------------------------------------------------------------------
class CompositeError(Exception):
    def __init__(
        self, exceptions: Iterable[Exception], msg: str = "Multiple errors occurred."
    ):
        self.exceptions = list(exceptions)
        super().__init__(self._compose_message(msg))

    def _compose_message(self, msg: str):
        sb = []
        sb.append(msg)

        for exc in self.exceptions:
            for line in str(exc).strip().split("\n"):
                sb.append("\t" + line)
        return "\n".join(sb)


# --------------------------------------------------------------------
RecipeComponents = Iterable["Recipe"] | dict[str, "Recipe" | Iterable["Recipe"]]


# --------------------------------------------------------------------
class Recipe:
    def __init__(
        self,
        components: RecipeComponents = {},
        *,
        setup: Optional["Recipe"] = None,
        name="Nameless Recipe",
        sync=False,
        memoize=False,
    ):
        if isinstance(components, dict):
            self.component_map = components or {}
        else:
            self.component_map = {"args": components}

        self.lock = asyncio.Lock()
        self.setup = setup
        self.name = name
        self.sync = sync
        self.memoize = memoize
        self.saved_result = None

    def _contextualize(self, s: str) -> str:
        return f"(for {self}) {s}"

    def log(self, event_name: str, data: Any = None):
        bus = EventBus.get()
        event = Event(event_name, self, data)
        bus.send(event)

    def error(self, msg) -> RuntimeError:
        exc = RuntimeError(self._contextualize(msg))
        self.log(Events.ERROR, exc)
        return exc

    def has_components(self):
        try:
            next(self.components())
            return True

        except StopIteration:
            return False

    def components(self) -> Generator["Recipe", None, None]:
        for c in self.component_map.values():
            if isinstance(c, Recipe):
                yield c
            else:
                yield from c

    def __iter__(self):
        yield from self.components()

    def composite_error(self, exceptions: Iterable[Exception], msg: str):
        exc = CompositeError(exceptions, self._contextualize(msg))
        self.log(Events.ERROR, exc)
        return exc

    def age(self, _: datetime) -> timedelta:
        return timedelta.max

    def component_age(self, ref: datetime) -> timedelta:
        if not self.has_components():
            return timedelta.max
        else:
            return min(min(c.age(ref), c.component_age(ref)) for c in self.components())

    def component_results(self) -> dict[str, Any]:
        results = {}

        for k, c in self.component_map.items():
            if isinstance(c, Recipe):
                results[k] = c.result()
            else:
                results[k] = [r.result() for r in c]

        return results

    def done(self) -> bool:
        return self.saved_result is not None

    def components_done(self) -> bool:
        return all(c.done() for c in self.components())

    def outdated(self, ref: datetime) -> bool:
        return self.age(ref) <= self.component_age(ref)

    async def clean(self):
        pass

    async def clean_components(self):
        results = await asyncio.gather(
            *(c.clean() for c in self.components()), return_exceptions=True
        )
        exceptions = [e for e in results if isinstance(e, Exception)]
        if exceptions:
            raise self.composite_error(
                exceptions, "Failed to clean one or more components."
            )

    async def make_components(self) -> Iterable[Any]:
        if self.sync:
            results = []
            for c in self.components():
                try:
                    results.append(await c())

                except Exception as e:
                    raise self.error("Failed to make component.") from e

            return results

        else:
            results = await asyncio.gather(
                *(c() for c in self.components()), return_exceptions=True
            )
            exceptions = [e for e in results if isinstance(e, Exception)]
            if exceptions:
                raise self.composite_error(
                    exceptions, "Failed to make one or more components."
                )
            return results

    async def make(self):
        return True

    def result(self):
        if self.saved_result is None:
            raise ValueError("Recipe result has not yet been recorded.")
        return self.saved_result

    async def __call__(self):
        async with self.lock:
            if self.memoize and self.saved_result is not None:
                return self.saved_result

            if self.setup is not None:
                try:
                    await self.setup()

                except Exception as e:
                    raise self.error("Setup method failed.") from e

            await self.make_components()
            result = await self.make()

            if result is None:
                raise self.error("Recipe make() function didn't return a value.")

            self.saved_result = result

            if not self.done():
                self.saved_result = None
                raise self.error("Recipe didn't complete successfully.")

            self.log(Events.SUCCESS)

            return result


# --------------------------------------------------------------------
class FileRecipe(Recipe):
    def __init__(
        self,
        target: str | Path,
        components: RecipeComponents = {},
        *,
        static=False,
        user: Optional["str"] = None,
        **kwargs,
    ):
        assert not (static and components), "Static files can't have components."
        super().__init__(components, **kwargs)
        self.target = Path(target)
        self.static = static
        self.user = user

    def age(self, ref: datetime) -> timedelta:
        if not self.target.exists():
            return timedelta.max
        return ref - datetime.fromtimestamp(self.target.stat().st_mtime)

    def done(self):
        return self.target.exists()

    async def clean(self):
        if self.static or not self.target.exists():
            return
        try:
            if self.user:
                result = Shell().interact_as(
                    self.user, ["rm", "-rf", str(self.target.absolute())]
                )
                if result != 0:
                    raise RuntimeError(
                        f"Failed to delete `f{self.target}` as `f{self.user}`."
                    )
            else:
                if self.target.is_dir():
                    shutil.rmtree(self.target)
                else:
                    self.target.unlink()

        except Exception as e:
            raise self.error("Failed to clean.") from e

        self.log(Events.CLEAN, self.target)

    async def make(self):
        return self.target


# --------------------------------------------------------------------
class Lambda(Recipe):
    ARGS = 0x1
    KWARGS = 0x4
    RESULTS = 0x8

    def __init__(
        self,
        f: Callable,
        components: RecipeComponents = {},
        pflags=0,
        **kwargs,
    ):
        if 'name' not in kwargs:
            kwargs = {**kwargs, 'name': f.__name__}
        super().__init__(components, **kwargs)
        self.f = f
        self.pflags = pflags

    async def make(self):
        if self.pflags & self.ARGS:
            if self.pflags & self.RESULTS:
                return await async_wrap(
                    self.f, *[c.result() for c in self.components()]
                )
            else:
                return await async_wrap(self.f, *self.components())

        elif self.pflags & self.KWARGS:
            if self.pflags & self.RESULTS:
                return await async_wrap(self.f, **self.component_results())
            else:
                return await async_wrap(self.f, **self.component_map)

        else:
            if self.pflags & self.RESULTS:
                return await async_wrap(self.f, list(self.components()))
            else:
                print(f'LRS-DEBUG: components = {list(self.components())}')
                return await async_wrap(self.f)
