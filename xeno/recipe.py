# --------------------------------------------------------------------
# recipe.py
#
# Author: Lain Musgrove (lain.proliant@gmail.com)
# Date: Thursday March 9, 2023
#
# Distributed under terms of the MIT license.
# --------------------------------------------------------------------

import asyncio
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

Predicate = Callable[[], bool]


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

    def error(self, msg) -> RuntimeError:
        return RuntimeError(self._contextualize(msg))

    def composite_error(self, exceptions: Iterable[Exception], msg: str):
        return CompositeError(exceptions, self._contextualize(msg))

    def age(self) -> timedelta:
        return timedelta.max

    def component_age(self) -> timedelta:
        if not self.components:
            return timedelta.max
        else:
            return min(c.age() for c in self.components)

    def done(self) -> bool:
        return (
            all(c.done() for c in self.components)
            and self.age() <= self.component_age()
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
            if self.setup is not None and not self.setup.done():
                try:
                    await self.setup()

                except Exception as e:
                    raise self.error("Setup method failed.") from e

            return await self.resolve()
