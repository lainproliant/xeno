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
from typing import Any, Iterable, Optional

from xeno.shell import Shell
from xeno.events import send_event


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
class Recipe:
    def __init__(
        self,
        components: Optional[Iterable["Recipe"]] = None,
        *,
        setup: Optional["Recipe"] = None,
        sync=False,
    ):
        self.components = list(components or [])
        self.lock = asyncio.Lock()
        self.setup = setup
        self.sync = sync

    def _contextualize(self, s: str) -> str:
        return f"(for {self}) {s}"

    def log(self, event: str, data: Any = None):
        send_event(event, self, data)

    def error(self, msg) -> RuntimeError:
        exc = RuntimeError(self._contextualize(msg))
        self.log(Events.ERROR, exc)
        return exc

    def composite_error(self, exceptions: Iterable[Exception], msg: str):
        exc = CompositeError(exceptions, self._contextualize(msg))
        self.log(Events.ERROR, exc)
        return exc

    def age(self, ref: datetime) -> timedelta:
        return timedelta.max

    def component_age(self, ref: datetime) -> timedelta:
        if not self.components:
            return timedelta.max
        else:
            return min(min(c.age(ref), c.component_age(ref)) for c in self.components)

    def done(self) -> bool:
        return True

    def components_done(self) -> bool:
        return all(c.done() for c in self.components)

    def outdated(self, ref: datetime) -> bool:
        return self.age(ref) <= self.component_age(ref)

    async def clean(self):
        pass

    async def clean_components(self):
        results = await asyncio.gather(
            *(c.clean() for c in self.components), return_exceptions=True
        )
        exceptions = [e for e in results if isinstance(e, Exception)]
        if exceptions:
            raise self.composite_error(
                exceptions, "Failed to clean one or more components."
            )

    async def resolve(self) -> Any:
        if self.sync:
            results = []
            for c in self.components:
                try:
                    results.append(await c())

                except Exception as e:
                    raise self.error("Failed to resolve component.") from e

            return results

        else:
            results = await asyncio.gather(
                *(c() for c in self.components), return_exceptions=True
            )
            exceptions = [e for e in results if isinstance(e, Exception)]
            if exceptions:
                raise self.composite_error(
                    exceptions, "Failed to resolve one or more components."
                )
            return results

    async def __call__(self) -> Any:
        async with self.lock:
            if self.setup is not None:
                try:
                    await self.setup()

                except Exception as e:
                    raise self.error("Setup method failed.") from e

            result = await self.resolve()
            if not self.done():
                raise self.error("Recipe didn't complete successfully.")

            self.log(Events.SUCCESS)
            return result


# --------------------------------------------------------------------
class FileRecipe(Recipe):
    def __init__(
        self,
        target: str | Path,
        components: Optional[Iterable["Recipe"]] = None,
        *,
        setup: Optional["Recipe"] = None,
        static=False,
        sync=False,
        user: Optional["str"] = None,
    ):
        assert not (static and components), "Static files can't have components."
        super().__init__(components, setup=setup, sync=sync)
        self.target = Path(target)
        self.static = static
        self.user = user

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

    def age(self, ref: datetime) -> timedelta:
        if not self.target.exists():
            return timedelta.max
        return ref - datetime.fromtimestamp(self.target.stat().st_mtime)
